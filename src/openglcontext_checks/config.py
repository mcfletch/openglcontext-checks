"""`[tool.openglcontext-checks]`: which rules run on which files.

The table is read from the nearest `pyproject.toml` that has one, searching
upwards from the starting directory; where none has the table, the nearest
`pyproject.toml` of any kind marks the project root and every setting takes
its default. The directory holding that file is the project root: configured
paths and globs are relative to it, and the result cache lives in it.

Keys:

- `paths`: what a run with no arguments checks (default `["."]`).
- `select`: rule codes or code prefixes to run (default: every rule).
- `ignore`: codes or prefixes taken out of `select`.
- `exclude`: globs never checked, added to the build, cache and environment
  directories that never are.
- `per-file-ignores`: a table of glob to codes not run on the files it matches.
- `scopes`: a table of scope name to globs; the `test` scope, which OGC221 to
  OGC223 run in, defaults to `tests/**`, `**/test_*.py`, `**/*_test.py` and
  `**/conftest.py`.

An unknown key, an unknown code or scope, or a value of the wrong type is a
`ConfigError`.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from collections.abc import Iterable, Mapping, Sequence

from .globs import matches
from .rules import ALL_RULES, RULES

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10, where tomli stands in for tomllib
    import tomli as tomllib

TABLE = 'openglcontext-checks'

#: Never checked, in any project: tool caches, environments and build output.
DEFAULT_EXCLUDE = (
    '.git',
    '.hg',
    '.svn',
    '.tox',
    '.nox',
    '.venv',
    'venv',
    '.eggs',
    '*.egg-info',
    '__pycache__',
    '.mypy_cache',
    '.ruff_cache',
    '.pytest_cache',
    '.oglc-check-cache',
    '_build',
    'build',
    'dist',
    'node_modules',
    'site-packages',
)

#: The globs each scope has where the configuration does not name its own.
DEFAULT_SCOPES: Mapping[str, tuple[str, ...]] = {
    'test': ('tests/**', '**/test_*.py', '**/*_test.py', '**/conftest.py'),
}

#: Every scope some rule runs in.
KNOWN_SCOPES = frozenset(rule.scope for rule in ALL_RULES if rule.scope)

_KEYS = frozenset({'paths', 'select', 'ignore', 'exclude', 'per-file-ignores', 'scopes'})


class ConfigError(Exception):
    """A configuration, or a command line, that cannot be run as written."""


@dataclasses.dataclass(frozen=True)
class Config:
    """The effective settings for one project."""

    #: The project root, absolute.
    root: str
    #: The pyproject.toml the settings came from, or None.
    source: str | None = None
    paths: tuple[str, ...] = ('.',)
    select: frozenset[str] = frozenset(RULES)
    ignore: frozenset[str] = frozenset()
    exclude: tuple[str, ...] = ()
    per_file_ignores: tuple[tuple[str, frozenset[str]], ...] = ()
    scopes: tuple[tuple[str, tuple[str, ...]], ...] = tuple(DEFAULT_SCOPES.items())

    @property
    def selected(self) -> tuple[str, ...]:
        """The codes that run, before any per-file ignore, in order."""
        return tuple(sorted(self.select - self.ignore))

    def codes_for(self, path: str) -> frozenset[str]:
        """The codes that run on the project-relative `path`."""
        codes = self.select - self.ignore
        for pattern, ignored in self.per_file_ignores:
            if matches(pattern, path):
                codes -= ignored
        return codes

    def scopes_for(self, path: str) -> frozenset[str]:
        """The scopes the project-relative `path` is in."""
        return frozenset(
            name
            for name, patterns in self.scopes
            if any(matches(pattern, path) for pattern in patterns)
        )

    def is_excluded(self, path: str) -> bool:
        """Whether the project-relative `path` is never checked."""
        return any(matches(pattern, path) for pattern in (*DEFAULT_EXCLUDE, *self.exclude))

    def settings_for(self, path: str) -> str:
        """Everything in the configuration that decides `path`'s findings, as text."""
        return '%s|%s' % (
            ','.join(sorted(self.codes_for(path))),
            ','.join(sorted(self.scopes_for(path))),
        )

    def with_overrides(self, *, select: Sequence[str] | None, ignore: Sequence[str]) -> Config:
        """These settings with a command line's codes: `select` replaces, `ignore` adds."""
        chosen = self.select if select is None else _expand(select, '--select')
        return dataclasses.replace(
            self, select=chosen, ignore=self.ignore | _expand(ignore, '--ignore')
        )


def load_config(start: str) -> Config:
    """The configuration for the project containing the directory `start`."""
    start = os.path.abspath(start)
    nearest: str | None = None
    for directory in _parents(start):
        candidate = os.path.join(directory, 'pyproject.toml')
        if not os.path.isfile(candidate):
            continue
        tool = _read(candidate).get('tool')
        table = tool.get(TABLE) if isinstance(tool, dict) else None
        if table is not None:
            return _from_table(table, directory, candidate)
        if nearest is None:
            nearest = candidate
    if nearest is None:
        return Config(root=start)
    return Config(root=os.path.dirname(nearest), source=nearest)


def _parents(start: str) -> list[str]:
    """`start` and each directory above it."""
    found = [start]
    while os.path.dirname(found[-1]) != found[-1]:
        found.append(os.path.dirname(found[-1]))
    return found


def _read(path: str) -> dict[str, object]:
    try:
        with open(path, 'rb') as handle:
            data: dict[str, object] = tomllib.load(handle)
            return data
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError('%s: cannot read: %s' % (path, error)) from error


def _from_table(table: object, root: str, source: str) -> Config:
    where = '%s [tool.%s]' % (source, TABLE)
    if not isinstance(table, dict):
        raise ConfigError('%s must be a table' % (where,))
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ConfigError('%s: unknown key %r' % (where, unknown[0]))
    try:
        paths = tuple(_strings(table.get('paths', ['.']), 'paths'))
        if not paths:
            raise ConfigError('paths must name at least one path')
        select = _expand(_strings(table.get('select', sorted(RULES)), 'select'), 'select')
        ignore = _expand(_strings(table.get('ignore', []), 'ignore'), 'ignore')
        exclude = tuple(_strings(table.get('exclude', []), 'exclude'))
        per_file = tuple(
            (pattern, _expand(_strings(codes, 'per-file-ignores.' + pattern), 'per-file-ignores'))
            for pattern, codes in _table(table.get('per-file-ignores', {}), 'per-file-ignores')
        )
        scopes = dict(DEFAULT_SCOPES)
        for name, patterns in _table(table.get('scopes', {}), 'scopes'):
            if name not in KNOWN_SCOPES:
                raise ConfigError(
                    'scopes: unknown scope %r (known: %s)' % (name, ', '.join(sorted(KNOWN_SCOPES)))
                )
            scopes[name] = tuple(_strings(patterns, 'scopes.' + name))
    except ConfigError as error:
        raise ConfigError('%s: %s' % (where, error)) from None
    return Config(
        root=root,
        source=source,
        paths=paths,
        select=select,
        ignore=ignore,
        exclude=exclude,
        per_file_ignores=per_file,
        scopes=tuple(scopes.items()),
    )


def _strings(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError('%s must be a list of strings' % (name,))
    return value


def _table(value: object, name: str) -> Iterable[tuple[str, object]]:
    if not isinstance(value, dict):
        raise ConfigError('%s must be a table' % (name,))
    return value.items()


def _expand(selectors: Iterable[str], name: str) -> frozenset[str]:
    """The rule codes `selectors` name: each a code or a prefix of at least one."""
    codes: set[str] = set()
    for selector in selectors:
        chosen = {
            code for code in RULES if selector.startswith('OGC') and code.startswith(selector)
        }
        if not chosen:
            raise ConfigError('%s: unknown rule code %r' % (name, selector))
        codes |= chosen
    return frozenset(codes)
