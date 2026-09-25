"""The findings of each file from the last run, so an unchanged file is not parsed.

One JSON file per project, `.oglc-check-cache/results.json` under the project
root, maps each checked file's project-relative path to a key and the findings
reported for it. The key is a hash of the file's bytes, of this package's own
source (which is what decides the findings, and changes in an editable install
without a new version number) and of the settings that decide the file's
findings (the codes that run on it, the scopes it is in and the project's
sanctioned names), so an edit to the
file, to the rules or to the configuration each make the entry miss. A hit reports the stored findings without reading the
syntax tree.

The file is replaced whole: written to a temporary file beside it, then moved
over it with one rename, so a reader never sees half of one. The directory
holds a `.gitignore` of `*`, which keeps it out of version control in any
project. A cache that cannot be read is treated as empty; one that cannot be
written is reported on standard error and the run carries on.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import secrets
import sys
from collections.abc import Sequence

from .findings import Finding

CACHE_DIRECTORY = '.oglc-check-cache'
_RESULTS = 'results.json'


_PACKAGE = os.path.dirname(os.path.abspath(__file__))


def implementation_digest(directory: str) -> str:
    """A hash of every Python source file under `directory`, by relative path."""
    digest = hashlib.sha256()
    for folder, subfolders, names in os.walk(directory):
        subfolders[:] = sorted(name for name in subfolders if name != '__pycache__')
        for name in sorted(names):
            if not name.endswith('.py'):
                continue
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, directory).replace(os.sep, '/')
            with open(path, 'rb') as handle:
                source = handle.read()
            for part in (relative.encode('utf-8'), source):
                digest.update(len(part).to_bytes(8, 'little'))
                digest.update(part)
    return digest.hexdigest()


@functools.cache
def implementation() -> str:
    """The digest of this package's source, read once a process."""
    return implementation_digest(_PACKAGE)


def entry_key(content: bytes, settings: str) -> str:
    """The key for a file with `content`, checked under `settings` by these rules."""
    digest = hashlib.sha256()
    for part in (implementation().encode('utf-8'), settings.encode('utf-8'), content):
        digest.update(len(part).to_bytes(8, 'little'))
        digest.update(part)
    return digest.hexdigest()


class ResultCache:
    """The stored findings for one project."""

    def __init__(self, root: str, *, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self.directory = os.path.join(root, CACHE_DIRECTORY)
        self._entries: dict[str, dict[str, object]] = self._load() if enabled else {}
        self._changed = False

    def lookup(self, path: str, key: str) -> list[Finding] | None:
        """The findings stored for the project-relative `path` under `key`, or None."""
        entry = self._entries.get(path)
        if entry is None or entry.get('key') != key:
            return None
        stored = entry.get('findings')
        if not isinstance(stored, list):
            return None
        return [Finding(*item) for item in stored]

    def store(self, path: str, key: str, findings: Sequence[Finding]) -> None:
        """Record `findings` for `path` under `key`."""
        if not self.enabled:
            return
        entry: dict[str, object] = {
            'key': key,
            'findings': [[f.line, f.column, f.code, f.message] for f in findings],
        }
        if self._entries.get(path) != entry:
            self._entries[path] = entry
            self._changed = True

    def save(self) -> None:
        """Write the cache if anything changed, dropping entries for files that are gone."""
        if not self._changed:
            return
        files = {
            path: entry
            for path, entry in sorted(self._entries.items())
            if os.path.exists(os.path.join(self.root, path))
        }
        text = json.dumps({'version': implementation(), 'files': files}, separators=(',', ':'))
        try:
            os.makedirs(self.directory, exist_ok=True)
            ignore = os.path.join(self.directory, '.gitignore')
            if not os.path.exists(ignore):
                self._replace(ignore, '*\n')
            self._replace(os.path.join(self.directory, _RESULTS), text)
        except OSError as error:
            print(
                'oglc-check: could not write the result cache in %s: %s' % (self.directory, error),
                file=sys.stderr,
            )
            return
        self._changed = False

    def _load(self) -> dict[str, dict[str, object]]:
        try:
            with open(os.path.join(self.directory, _RESULTS), encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get('version') != implementation():
            return {}
        files = data.get('files')
        return files if isinstance(files, dict) else {}

    def _replace(self, path: str, text: str) -> None:
        """Write `path` whole: a temporary file beside it, then one rename.

        The temporary file is created exclusively, with the permissions the
        user's umask gives any new file.
        """
        temporary = os.path.join(self.directory, '.tmp-%d-%s' % (os.getpid(), secrets.token_hex(6)))
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                handle.write(text)
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
