"""OGC111: a file opened at a path joined from a name nothing has contained."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .ogc101_bare_document_conversion import named_field
from .paths import assigned, fixed, parts, unwrap

if TYPE_CHECKING:
    from ..engine import Module
    from ..symbols import Symbols

#: The openers of a file by path.
_OPENERS = frozenset(
    {
        'builtins.open',
        'io.open',
        'codecs.open',
        'gzip.open',
        'bz2.open',
        'lzma.open',
        'tarfile.open',
        'zipfile.ZipFile',
        'PIL.Image.open',
        'numpy.load',
        'numpy.fromfile',
    }
)

#: The keywords an opener takes its path as.
_PATH_KEYWORDS = frozenset({'file', 'filename', 'name', 'fp'})


class UnconfinedPath(Rule):
    """A file opened at a path the function joined from a name it did not contain.

    Reported, in the `loader` scope: an opener (`open`, `io.open`,
    `codecs.open`, `gzip`, `bz2` and `lzma`'s `open`, `tarfile.open`,
    `zipfile.ZipFile`, `PIL.Image.open`, `numpy.load`, `numpy.fromfile`)
    handed a path that the same function joins (`os.path.join`, a path class
    given several parts, `+`, `/`, `%` or `str.format` on a literal
    template, an f-string) where a part after the first is not fixed by the
    source, or a path read from a document's named field
    (`material['texture']`). A local name is followed through everything the
    function assigns it. A name a document gives (`../../etc/passwd`, an
    absolute path, a link out) opens whatever it names.

    A part is fixed when it is a literal, a name of the module (a constant or
    an import), or a local assigned only fixed values or walking a literal
    sequence. The base a name is joined under may be anything, and a
    parameter, an attribute or the result of any other call opened as it is
    is not reported: where it came from is decided outside the function.

    Use instead: resolve the name against the document's base, which refuses
    a name that leads outside it. In OpenGLContext that is
    `loaders.resolver.Resolver` (`resolve`, `fetch`) and
    `loaders.tiles3d.fetch.beside` (with `local_copy` for a served world); a
    project names its own in `sanctioned`.
    """

    code = 'OGC111'
    name = 'raw opener on an unconfined path'
    scope = 'loader'
    nodes = (ast.Call,)
    sanctioned = (
        'OpenGLContext.loaders.resolver.Resolver.resolve',
        'OpenGLContext.loaders.tiles3d.fetch.beside',
    )

    VALID = (
        snippet("""
            from OpenGLContext.loaders.tiles3d import fetch

            def read_zones(base, extras):
                where = fetch.local_copy(fetch.beside(base, extras['zones']))
                with open(where, 'rb') as handle:
                    return handle.read()
        """),
        snippet("""
            import os

            def read_sample(directory):
                with open(os.path.join(directory, 'ground.glb'), 'rb') as handle:
                    return handle.read()
        """),
        snippet("""
            def load(path):
                with open(path, 'rb') as handle:
                    return handle.read()
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                import os
                from PIL import Image

                def read_cover(directory, species):
                    card = Image.open(os.path.join(directory, species['card']))
                    with open(directory + '/' + species['clump'], 'rb') as handle:
                        clump = handle.read()
                    bark = open(species['bark'], 'rb')
                    return card, clump, bark
            """),
            (5, 6, 8),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        if symbols.qualified_name(node.func) not in _OPENERS:
            return
        path = _path(node)
        if path is None:
            return
        found = _built(path, symbols, frozenset())
        if found is None:
            return
        how, part = found
        yield self.finding(
            node,
            '%s() opens a path %s %s: a name a document gives can lead outside the '
            "document's directory (a '..', an absolute path, a link); resolve it against "
            'that directory, which refuses one that leaves it (%s)'
            % (
                ast.unparse(node.func),
                how,
                ast.unparse(part),
                ' or '.join(self.sanctioned_names(module)),
            ),
        )


def _path(node: ast.Call) -> ast.expr | None:
    """The path `node` opens: its first argument, or the keyword naming it."""
    if node.args:
        first = node.args[0]
        return None if isinstance(first, ast.Starred) else first
    for passed in node.keywords:
        if passed.arg in _PATH_KEYWORDS:
            return passed.value
    return None


def _built(node: ast.expr, symbols: Symbols, seen: frozenset[str]) -> tuple[str, ast.expr] | None:
    """How the function built `node` from something unfixed, and from what; None if not."""
    node = unwrap(node, symbols)
    if isinstance(node, ast.IfExp):
        return _built(node.body, symbols, seen) or _built(node.orelse, symbols, seen)
    if named_field(node, symbols):
        return 'read from', node
    joined = parts(node, symbols)
    if joined is not None:
        for part in joined[1:]:
            if not fixed(part, symbols):
                return 'joined from', part
        return _built(joined[0], symbols, seen)
    if isinstance(node, ast.Name) and node.id not in seen:
        for value in assigned(node, symbols) or ():
            found = _built(value, symbols, seen | {node.id})
            if found is not None:
                return found
    return None
