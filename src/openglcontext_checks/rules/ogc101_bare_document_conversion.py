"""OGC101: a document's value converted with a bare `float`, `int` or `bool`."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .paths import fixed

if TYPE_CHECKING:
    from ..engine import Module
    from ..symbols import Symbols

_CONVERSIONS = frozenset({'builtins.float', 'builtins.int', 'builtins.bool'})


class BareDocumentConversion(Rule):
    """A named field of a document converted with a bare `float`, `int` or `bool`.

    Reported, in the `loader` scope: a call to the builtin `float`, `int` or
    `bool` whose first argument is a subscript by a string literal
    (`extras['depth']`) or a `get` call whose first argument is a string
    literal (`params.get('count', 0)`). A value read out of a model, a
    tileset, a registry or a settings file is whatever the file says: a
    misspelt word raises and aborts the load, `1e999` and `nan` pass `float`
    and reach an allocation or a draw, a count of four billion passes `int`,
    and `bool('false')` is true.

    Not reported: an index by a number or a variable (`shape[0]`,
    `values[key]`), which is a sequence or a table the program built; a field
    of a table the module itself holds (a constant it defines or imports); and a
    conversion outside the `loader` scope, which a project gives the modules
    that read documents.

    Use instead: a reader that checks the value, reports it once, and answers
    a default or a clamped value. In OpenGLContext that is
    `loaders.documentvalues.DocumentValues` (`number`, `integer`, `flag`,
    `choice`, `vector`); a project names its own in `sanctioned`. The module
    implementing it converts values itself, and a `per-file-ignores` entry
    exempts it.
    """

    code = 'OGC101'
    name = 'bare conversion of a document value'
    scope = 'loader'
    nodes = (ast.Call,)
    sanctioned = ('OpenGLContext.loaders.documentvalues.DocumentValues',)

    VALID = (
        snippet("""
            from OpenGLContext.loaders.documentvalues import DocumentValues

            def read_water(params, log):
                values = DocumentValues(logger=log)
                depth = values.number(params.get('depth'), 0.0, 'water depth', minimum=0.0)
                hemi = values.flag(params.get('hemi'), True, 'impostor hemisphere')
                return depth, hemi
        """),
        snippet("""
            def corners(shape, positions):
                rows = int(shape[0])
                return [float(positions[index]) for index in range(rows)]
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                def read_emitter(extras):
                    rate = float(extras['rate'])
                    most = int(extras.get('maxParticles', 100))
                    hemi = bool(extras.get('hemi'))
                    return rate, most, hemi
            """),
            (2, 3, 4),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        qualified = module.symbols.qualified_name(node.func)
        if qualified not in _CONVERSIONS or not node.args:
            return
        field = node.args[0]
        if not named_field(field, module.symbols):
            return
        yield self.finding(
            node,
            '%s() of %s: a value read from a document can be missing, misspelt, infinite '
            'or out of range, which aborts the load or reaches an allocation; read it '
            'through a checking reader that reports it and answers a default (%s)'
            % (
                qualified.rpartition('.')[2],
                ast.unparse(field),
                ' or '.join(self.sanctioned_names(module)),
            ),
        )


def named_field(node: ast.expr, symbols: Symbols) -> bool:
    """Whether `node` reads a field named by a string literal from a mapping it was handed.

    A table the module itself holds (a constant, or a name it imports) is the
    program's own data rather than a document's.
    """
    if isinstance(node, ast.Subscript):
        key, table = node.slice, node.value
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'get'
        and node.args
    ):
        key, table = node.args[0], node.func.value
    else:
        return False
    return (
        isinstance(key, ast.Constant) and isinstance(key.value, str) and not fixed(table, symbols)
    )
