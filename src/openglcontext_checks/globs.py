"""Matching project-relative paths against the globs a configuration names.

Paths are relative to the project root and written with `/`. A pattern with no
`/` matches any one component of the path, so `build` matches a directory of
that name at any depth and `test_*.py` a file of that name anywhere. A pattern
with a `/` is anchored at the project root (a leading `./` or `/` is dropped),
and matches the path or any directory above it, so `docs/_build` covers
everything beneath that directory. `*` and `?` match within one component,
`[...]` is a character class (`[!...]` negated), and a `**` component matches
any number of directories, including none.
"""

from __future__ import annotations

import functools
import re


def matches(pattern: str, path: str) -> bool:
    """Whether the project-relative `path` matches `pattern`."""
    return _compile(pattern).search(path) is not None


@functools.lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    if '/' not in pattern.strip('/'):
        return re.compile(r'(?:^|/)%s(?:/|$)' % (_component(pattern.strip('/')),))
    parts = pattern.removeprefix('./').strip('/').split('/')
    expression = ''
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == '**':
            expression += '.*' if last else '(?:[^/]+/)*'
        else:
            expression += _component(part) + ('' if last else '/')
    return re.compile(r'^%s(?:/.*)?$' % (expression,))


def _component(part: str) -> str:
    """The expression for one path component of a glob."""
    expression = ''
    index = 0
    while index < len(part):
        character = part[index]
        closing = part.find(']', index + 2) if character == '[' else -1
        if character == '*':
            expression += '[^/]*'
        elif character == '?':
            expression += '[^/]'
        elif closing != -1:
            inside = part[index + 1 : closing]
            if inside.startswith('!'):
                inside = '^' + inside[1:]
            expression += '[%s]' % (inside.replace('\\', '\\\\'),)
            index = closing
        else:
            expression += re.escape(character)
        index += 1
    return expression
