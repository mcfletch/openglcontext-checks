"""OGC102: a decode or an allocation sized by a document before any check of its size."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .ogc101_bare_document_conversion import named_field
from .paths import region, statements_of

if TYPE_CHECKING:
    from ..engine import Module

#: The decoders, each sized by what it is handed as its first argument.
_DECODERS = frozenset(
    {
        'base64.b64decode',
        'base64.standard_b64decode',
        'base64.urlsafe_b64decode',
        'base64.b32decode',
        'base64.b16decode',
        'base64.a85decode',
        'base64.b85decode',
        'base64.decodebytes',
        'binascii.a2b_base64',
        'zlib.decompress',
        'gzip.decompress',
        'bz2.decompress',
        'lzma.decompress',
        'DracoPy.decode',
    }
)

#: The allocations, with where each takes the numbers that size it.
_ALLOCATIONS: dict[str, tuple[tuple[int, str], ...]] = {
    'numpy.frombuffer': ((2, 'count'), (3, 'offset')),
    'numpy.empty': ((0, 'shape'),),
    'numpy.zeros': ((0, 'shape'),),
    'numpy.ones': ((0, 'shape'),),
    'numpy.full': ((0, 'shape'),),
}


class DecodeBeforeSizeCheck(Rule):
    """Bytes decoded, or an array allocated, at a size a document chose, unchecked.

    Reported, in the `loader` scope: a call to a decoder (`base64`'s
    decoders, `binascii.a2b_base64`, `zlib`, `gzip`, `bz2` and `lzma`'s
    `decompress`, `DracoPy.decode`) whose input is a value of the function
    (a parameter or a local, not the module's own data), and a
    `numpy.frombuffer` count or offset, or a `numpy.empty`, `zeros`, `ones`
    or `full` shape, that reads a document's named field (`accessor['count']`)
    -- where nothing earlier in the function compares one of the names that
    value is made of, or hands one to a sanctioned size check. A document
    that names a size of four billion, or a payload that decodes to
    gigabytes, allocates it before anything refuses it.

    The check is by name: an earlier comparison that mentions the value's
    parameter or local (`if len(payload) > cap`, `if end > len(data)`)
    counts, wherever it is in the function before the decode.

    Use instead: compare the size with a cap first. In OpenGLContext that is
    `loaders.resolver.check_size` or `check_pixels`, or
    `resolver.decode_data_uri(uri, max_bytes)` for a data URI; a project
    names its own checks in `sanctioned`.
    """

    code = 'OGC102'
    name = 'decode before a size check'
    scope = 'loader'
    nodes = (ast.Call,)
    sanctioned = (
        'OpenGLContext.loaders.resolver.check_size',
        'OpenGLContext.loaders.resolver.check_pixels',
    )

    VALID = (
        snippet("""
            import base64
            from OpenGLContext.loaders.resolver import check_size

            def decode(payload, most):
                check_size(len(payload) * 3 // 4, most, 'data: URI')
                return base64.b64decode(payload)
        """),
        snippet("""
            import DracoPy

            def draco(data, start, end):
                if end > len(data):
                    raise ValueError('the view reads past its buffer')
                return DracoPy.decode(bytes(data[start:end]))
        """),
        snippet("""
            import numpy

            def read(data, accessor, most):
                if accessor['count'] > most:
                    raise ValueError('too many elements')
                return numpy.frombuffer(data, numpy.float32, accessor['count'])
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                import base64, zlib
                import numpy as np

                def read(payload, accessor, view, data):
                    raw = base64.b64decode(payload)
                    unpacked = zlib.decompress(raw)
                    return np.frombuffer(data, np.float32, accessor['count'], view['byteOffset'])
            """),
            (5, 6, 7),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        qualified = symbols.qualified_name(node.func)
        if qualified in _DECODERS:
            if not node.args:
                return
            sizing = [node.args[0]]
        elif qualified in _ALLOCATIONS:
            sizing = [
                value
                for position, keyword in _ALLOCATIONS[qualified]
                for value in _argument(node, position, keyword)
                if any(
                    named_field(inner, symbols)
                    for inner in ast.walk(value)
                    if isinstance(inner, ast.expr)
                )
            ]
        else:
            return
        names = {
            inner.id
            for value in sizing
            for inner in ast.walk(value)
            if isinstance(inner, ast.Name) and _local(inner, module)
        }
        if not names or _checked_before(node, names, self.sanctioned_names(module), module):
            return
        yield self.finding(
            node,
            '%s is sized by a value the document chose, and nothing before it compares '
            'that size with a cap: a document naming gigabytes allocates them before '
            'anything refuses it; check the size first (%s)'
            % (ast.unparse(node), ' or '.join(self.sanctioned_names(module))),
        )


def _argument(node: ast.Call, position: int, keyword: str) -> list[ast.expr]:
    """The argument `node` passes at `position` or as `keyword`, if any."""
    if len(node.args) > position:
        return [node.args[position]]
    return [passed.value for passed in node.keywords if passed.arg == keyword]


def _local(name: ast.Name, module: Module) -> bool:
    """Whether `name` is a parameter or a local of a function."""
    scope = module.symbols.binding_scope(name)
    return scope is not None and not isinstance(scope, ast.Module | ast.ClassDef)


def _checked_before(
    node: ast.Call, names: set[str], checks: tuple[str, ...], module: Module
) -> bool:
    """Whether the function compares, or size-checks, one of `names` before `node`."""
    where = (node.lineno, node.col_offset)
    for earlier in statements_of(region(node, module.symbols)):
        if not isinstance(earlier, ast.Compare | ast.Call):
            continue
        if (earlier.lineno, earlier.col_offset) >= where:
            continue
        if isinstance(earlier, ast.Call):
            if module.symbols.qualified_name(earlier.func) not in checks:
                continue
            mentioned = [*earlier.args, *(passed.value for passed in earlier.keywords)]
        else:
            mentioned = [earlier.left, *earlier.comparators]
        if any(
            isinstance(inner, ast.Name) and inner.id in names
            for value in mentioned
            for inner in ast.walk(value)
        ):
            return True
    return False
