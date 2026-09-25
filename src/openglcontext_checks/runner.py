"""Finding a project's files and checking them, from the cache where it can.

`discover` turns paths into the Python files under them, less what the
configuration excludes. `check_files` reads each file, answers it from the
result cache where the file and its settings are unchanged, and checks the
rest: in one process for a handful of files, and across worker processes once
there are `PARALLEL_THRESHOLD` or more, where the cost of starting them is
repaid.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import os
from collections.abc import Sequence

from .cache import ResultCache, entry_key
from .config import Config, ConfigError
from .engine import ParseError, parse_module, run_rules
from .findings import Finding
from .rules import RULES

#: The number of files to check at which the work is spread over processes.
PARALLEL_THRESHOLD = 48
#: The most worker processes a run starts by default.
MAXIMUM_JOBS = 8

#: One file to check: its project-relative path, its bytes, the codes that run
#: on it, and the scopes it is in.
_Task = tuple[str, bytes, frozenset[str], frozenset[str]]


@dataclasses.dataclass
class Report:
    """What a run found."""

    #: (path as the caller should see it, finding), in path and line order.
    findings: list[tuple[str, Finding]]
    #: Files that could not be read or parsed, one message each.
    errors: list[str]
    #: How many files were checked, and how many of them had to be parsed.
    files: int
    parsed: int


def discover(config: Config, paths: Sequence[str] | None, cwd: str) -> list[str]:
    """The absolute paths of the Python files to check, sorted.

    With no `paths`, the configuration's own, relative to the project root;
    otherwise `paths`, relative to `cwd`. A directory contributes every `.py`
    file beneath it and a file is taken as named; the configuration's
    exclusions apply to both. Raises `ConfigError` for a path that does not
    exist.
    """
    if paths is None:
        named = [os.path.join(config.root, path) for path in config.paths]
    else:
        named = [os.path.join(cwd, path) for path in paths]
    found: set[str] = set()
    for path in named:
        path = os.path.normpath(path)
        if os.path.isdir(path):
            for directory, subdirectories, files in os.walk(path):
                subdirectories[:] = sorted(
                    name
                    for name in subdirectories
                    if not config.is_excluded(_relative(config, os.path.join(directory, name)))
                )
                found.update(
                    os.path.join(directory, name) for name in files if name.endswith('.py')
                )
        elif os.path.exists(path):
            found.add(path)
        else:
            raise ConfigError('no such file or directory: %s' % (path,))
    return sorted(path for path in found if not config.is_excluded(_relative(config, path)))


def check_files(
    config: Config,
    files: Sequence[str],
    *,
    cwd: str,
    cache: bool = True,
    jobs: int | None = None,
) -> Report:
    """Check `files` (absolute paths) under `config`; paths are reported from `cwd`."""
    results = ResultCache(config.root, enabled=cache)
    findings: list[tuple[str, Finding]] = []
    errors: list[str] = []
    tasks: list[_Task] = []
    keys: dict[str, str] = {}
    shown: dict[str, str] = {}
    for path in files:
        relative = _relative(config, path)
        shown[relative] = _shown(path, cwd)
        try:
            with open(path, 'rb') as handle:
                content = handle.read()
        except OSError as error:
            errors.append('%s: cannot read: %s' % (shown[relative], error.strerror or error))
            continue
        key = entry_key(content, config.settings_for(relative))
        stored = results.lookup(relative, key)
        if stored is not None:
            findings.extend((shown[relative], finding) for finding in stored)
            continue
        keys[relative] = key
        tasks.append((relative, content, config.codes_for(relative), config.scopes_for(relative)))
    for relative, outcome in _run(tasks, jobs):
        if isinstance(outcome, ParseError):
            errors.append(
                '%s:%d:%d: cannot parse: %s'
                % (shown[relative], outcome.line, outcome.column, outcome.message)
            )
            continue
        results.store(relative, keys[relative], outcome)
        findings.extend((shown[relative], finding) for finding in outcome)
    results.save()
    findings.sort(key=lambda item: (item[0], item[1]))
    return Report(findings, sorted(errors), len(files), len(tasks))


def _run(tasks: list[_Task], jobs: int | None) -> list[tuple[str, list[Finding] | ParseError]]:
    workers = jobs if jobs is not None else min(os.cpu_count() or 1, MAXIMUM_JOBS)
    if len(tasks) < PARALLEL_THRESHOLD or workers < 2:
        return [_check(task) for task in tasks]
    chunk = max(1, len(tasks) // (workers * 4))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_check, tasks, chunksize=chunk))


def _check(task: _Task) -> tuple[str, list[Finding] | ParseError]:
    """One file's findings, or why it could not be parsed; run in a worker."""
    relative, content, codes, scopes = task
    try:
        module = parse_module(content, relative, scopes)
    except ParseError as error:
        return relative, error
    return relative, run_rules(module, [RULES[code] for code in sorted(codes)])


def _relative(config: Config, path: str) -> str:
    """`path` relative to the project root, with `/` separators."""
    return os.path.relpath(path, config.root).replace(os.sep, '/')


def _shown(path: str, cwd: str) -> str:
    """`path` as a user in `cwd` would name it."""
    try:
        return os.path.relpath(path, cwd)
    except ValueError:  # another drive, on Windows
        return path
