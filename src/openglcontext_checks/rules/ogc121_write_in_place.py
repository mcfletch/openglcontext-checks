"""OGC121: a file written in place."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .paths import base, region, statements_of

if TYPE_CHECKING:
    from ..engine import Module

#: The openers of a stream, with where each takes its path and its mode.
_STREAMS: dict[str, tuple[tuple[int, str], tuple[int, str]]] = {
    'builtins.open': ((0, 'file'), (1, 'mode')),
    'io.open': ((0, 'file'), (1, 'mode')),
    'codecs.open': ((0, 'filename'), (1, 'mode')),
    'gzip.open': ((0, 'filename'), (1, 'mode')),
    'bz2.open': ((0, 'filename'), (1, 'mode')),
    'lzma.open': ((0, 'filename'), (1, 'mode')),
}

#: The openers of an archive, which rewrite its index to add a member too.
_ARCHIVES: dict[str, tuple[tuple[int, str], tuple[int, str]]] = {
    'tarfile.open': ((0, 'name'), (1, 'mode')),
    'zipfile.ZipFile': ((0, 'file'), (1, 'mode')),
}

#: The copies, with where each takes its destination.
_COPIES: dict[str, tuple[int, str]] = {
    'shutil.copy': (1, 'dst'),
    'shutil.copy2': (1, 'dst'),
    'shutil.copyfile': (1, 'dst'),
    'shutil.copytree': (1, 'dst'),
}

#: `pathlib.Path`'s methods that replace a file's content.
_PATH_WRITES = frozenset({'write_text', 'write_bytes'})

#: The letters an `open` mode is made of; a literal with any other is a name.
_MODE_LETTERS = frozenset('rwxabt+')

#: The calls whose result is a directory or file only this process writes.
_TEMPORARY = frozenset({'tempfile.mkdtemp', 'tempfile.mkstemp', 'tempfile.TemporaryDirectory'})

#: The calls that move a finished file over the one a reader opens.
_RENAMES = frozenset({'os.replace', 'os.rename'})


class WriteInPlace(Rule):
    """A file written where a reader will look for it, while it is written.

    Reported: `open` and `io.open`, `codecs.open`, `gzip.open`, `bz2.open`
    and `lzma.open` with a literal mode that writes over what the file holds
    (`w`, `x`, or `+` other than to append), `tarfile.open` and
    `zipfile.ZipFile` with a mode that writes (`w`, `a` or `x`); `shutil.copy`, `copy2`, `copyfile`
    and `copytree` to a destination; and `write_text`, `write_bytes`, or
    `open` with a literal mode that writes, called on anything that is not an
    imported module (a `pathlib.Path`). A write
    cut short (a full disk, a crash, Ctrl-C, a killed thread) leaves part of
    the file, and the next run takes it for the whole: a cache entry, a
    record, a settings file, an install marker.

    Not reported: a write under a directory, or to a file, that a sanctioned
    staging call made (a `with` target or an assigned result, followed
    through joins and local names), or that `tempfile.mkdtemp`, `mkstemp` or
    `TemporaryDirectory` made; a write to a name the same function then
    moves into place with `os.replace` or `os.rename` (or the path's own
    `replace` or `rename`); a mode that is not a literal; a stream opened
    to append, which keeps what it held (a log, a journal, a lock file) and
    has no staged form. Not run on the
    `test` scope, whose files are the test's own.

    Use instead: stage the file and move it into place with one rename. In
    OpenGLContext that is `atomicfiles.staged_file` (a handle to write) and
    `staged_directory` (a directory to fill), or `write_bytes`, `write_text`
    and `copy_file`. The sanctioned names are the staging calls, and a
    project names its own in `sanctioned`.
    """

    code = 'OGC121'
    name = 'file written in place'
    exempt_scope = 'test'
    nodes = (ast.Call,)
    sanctioned = (
        'OpenGLContext.atomicfiles.staged_file',
        'OpenGLContext.atomicfiles.staged_directory',
    )

    VALID = (
        snippet("""
            import json
            from OpenGLContext import atomicfiles

            def save(path, record):
                with atomicfiles.staged_file(path, 'w') as handle:
                    json.dump(record, handle)
        """),
        snippet("""
            import os
            from OpenGLContext.atomicfiles import staged_directory

            def install(where, members):
                with staged_directory(where) as staging:
                    for name, data in members:
                        with open(os.path.join(staging, name), 'wb') as handle:
                            handle.write(data)
        """),
        snippet("""
            import os

            def save(path, text):
                partial = path + '.partial'
                with open(partial, 'w') as handle:
                    handle.write(text)
                os.replace(partial, path)
        """),
        snippet("""
            import os
            import tempfile

            def render(scene):
                with tempfile.TemporaryDirectory() as scratch:
                    target = os.path.join(scratch, 'frame.png')
                    with open(target, 'wb') as handle:
                        handle.write(scene.png())
        """),
        snippet("""
            from OpenGLContext import atomicfiles

            def load(path):
                with open(path) as handle:
                    return handle.read()

            def save(path, text):
                atomicfiles.write_text(path, text)
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                import json

                def save(path, record):
                    with open(path, 'w') as handle:
                        json.dump(record, handle)
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                import pathlib

                def save(self, text):
                    pathlib.Path(self.where).write_text(text)
                    self.marker.write_bytes(b'done')
            """),
            (4, 5),
        ),
        Invalid(
            snippet("""
                import gzip, shutil, tarfile, zipfile

                def publish(source, where, log):
                    shutil.copyfile(source, where + '/model.glb')
                    with open(where + '.json', mode='x') as handle:
                        handle.write('published')
                    gzip.open(where + '.gz', 'wb').close()
                    tarfile.open(where + '.tar', 'w:gz').close()
                    zipfile.ZipFile(where + '.zip', mode='w').close()
            """),
            (4, 5, 7, 8, 9),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        written = self._written(node, module)
        if written is None:
            return
        what, path, method = written
        stagers = frozenset(self.sanctioned_names(module)) | _TEMPORARY
        if all(_staged(found, stagers, module) for found in base(path, symbols)):
            return
        if _renamed(path, node, module, methods=method):
            return
        yield self.finding(
            node,
            '%s writes %s in place: a write cut short leaves part of it, which the next '
            'reader takes for the whole; write it beside its path and rename it into place '
            '(%s)' % (what, ast.unparse(path), ' or '.join(self.sanctioned_names(module))),
        )

    def _written(self, node: ast.Call, module: Module) -> tuple[str, ast.expr, bool] | None:
        """What `node` writes, the path it writes to and whether that is a
        `pathlib.Path` written through its own method; None when it does not write."""
        qualified = module.symbols.qualified_name(node.func)
        openers = _STREAMS if qualified in _STREAMS else _ARCHIVES
        if qualified in openers:
            where, how = openers[qualified]
            path, mode = _argument(node, *where), _argument(node, *how)
            if (
                path is not None
                and isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and _rewrites(mode.value, archive=openers is _ARCHIVES)
            ):
                return '%s(..., %r)' % (ast.unparse(node.func), mode.value), path, False
            return None
        if qualified in _COPIES:
            destination = _argument(node, *_COPIES[qualified])
            if destination is not None:
                return ast.unparse(node.func), destination, False
            return None
        if (
            qualified is not None
            or not isinstance(node.func, ast.Attribute)
            or module.symbols.qualified_name(node.func.value) is not None
        ):
            return None
        if node.func.attr in _PATH_WRITES:
            return node.func.attr, node.func.value, True
        if node.func.attr == 'open':
            mode = _argument(node, 0, 'mode')
            if (
                isinstance(mode, ast.Constant)
                and isinstance(mode.value, str)
                and set(mode.value) <= _MODE_LETTERS
                and _rewrites(mode.value, archive=False)
            ):
                return 'open(..., %r)' % (mode.value,), node.func.value, True
        return None


def _rewrites(mode: str, *, archive: bool) -> bool:
    """Whether opening with `mode` writes over what the file holds.

    A stream opened to append keeps what it held (a log, a journal, a lock
    file), and has no staged form; an archive opened to append rewrites its
    index.
    """
    if archive:
        return bool(set(mode) & set('wax'))
    return 'w' in mode or 'x' in mode or ('+' in mode and 'a' not in mode)


def _argument(node: ast.Call, position: int, keyword: str) -> ast.expr | None:
    """The argument `node` passes at `position` or as `keyword`, or None."""
    if len(node.args) > position and not any(
        isinstance(argument, ast.Starred) for argument in node.args[: position + 1]
    ):
        return node.args[position]
    for passed in node.keywords:
        if passed.arg == keyword:
            return passed.value
    return None


def _staged(found: ast.expr, stagers: frozenset[str], module: Module) -> bool:
    """Whether the base `found` is the result of a staging or temporary-file call."""
    return isinstance(found, ast.Call) and module.symbols.qualified_name(found.func) in stagers


def _renamed(path: ast.expr, node: ast.Call, module: Module, *, methods: bool) -> bool:
    """Whether the function writing `path` moves it over another path.

    With `methods`, `path` is a `pathlib.Path`, and its own `replace` or
    `rename` counts too.
    """
    written = ast.dump(path)
    for later in statements_of(region(node, module.symbols)):
        if not isinstance(later, ast.Call) or not later.args:
            continue
        qualified = module.symbols.qualified_name(later.func)
        if qualified in _RENAMES and ast.dump(later.args[0]) == written:
            return True
        if (
            methods
            and qualified is None
            and isinstance(later.func, ast.Attribute)
            and later.func.attr in ('replace', 'rename')
            and ast.dump(later.func.value) == written
        ):
            return True
    return False
