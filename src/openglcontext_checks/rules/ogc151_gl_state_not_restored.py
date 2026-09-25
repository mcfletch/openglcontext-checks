"""OGC151: GL state changed in pass code with nothing restoring it on every exit."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .gl import gl_function
from .paths import region

if TYPE_CHECKING:
    from ..engine import Module
    from ..symbols import Symbols

#: The state changes, each by the family of calls that restores it.
_FAMILIES = {
    'glEnable': 'capability',
    'glDisable': 'capability',
    'glBindFramebuffer': 'glBindFramebuffer',
    'glScissor': 'glScissor',
    'glUseProgram': 'glUseProgram',
    'glCullFace': 'glCullFace',
}

#: The families whose restore must name the same first argument.
_BY_ARGUMENT = frozenset({'capability'})

_BLOCKS = ('body', 'orelse', 'finalbody', 'handlers')


class GlStateNotRestored(Rule):
    """A GL state change in pass code that an exception would leave in place.

    Reported, in the `pass` scope: a call to `glEnable`, `glDisable`,
    `glBindFramebuffer`, `glScissor`, `glUseProgram` or `glCullFace` (from
    `OpenGL.GL` or a GLES module, through any import form) unless the same
    function restores it in a `finally`: a `try` whose `finally` calls the
    same function again (for `glEnable` and `glDisable`, either of them, on
    the same capability) and which either holds the change in its body or
    handlers, or comes after it in the same block or a block around it. A
    call inside a `finally` is itself a restore, and a call inside a `with`
    of a sanctioned state manager is restored by the manager.

    A draw that raises part way leaves the state it set: scissoring stays on
    for the next view, a framebuffer stays bound as the next frame's target,
    culling stays reversed for the next pass. Restoring it at the end of the
    function, outside a `finally`, restores it only when nothing raised.

    Use instead: restore it in a `finally`, or through a context manager
    that restores it on exit. A project names its state managers in
    `sanctioned`; the module implementing them changes state itself, and a
    `per-file-ignores` entry exempts it.
    """

    code = 'OGC151'
    name = 'GL state change not restored'
    scope = 'pass'
    nodes = (ast.Call,)
    sanctioned = ()

    VALID = (
        snippet("""
            from OpenGL.GL import GL_SCISSOR_TEST, glDisable, glEnable, glScissor

            def draw_view(view, scene):
                glEnable(GL_SCISSOR_TEST)
                try:
                    glScissor(*view.rectangle)
                    scene.render(view)
                finally:
                    glDisable(GL_SCISSOR_TEST)
        """),
        snippet("""
            import contextlib
            from OpenGL import GL

            @contextlib.contextmanager
            def bound_framebuffer(fbo):
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
                try:
                    yield fbo
                finally:
                    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                from OpenGL.GL import *

                def draw_view(view, scene):
                    glEnable(GL_SCISSOR_TEST)
                    glScissor(*view.rectangle)
                    scene.render(view)
                    glDisable(GL_SCISSOR_TEST)
            """),
            (4, 5, 7),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        function = gl_function(node, symbols)
        if function not in _FAMILIES:
            return
        if _restored(node, _keys(function, node), symbols) or _managed(
            node, self.sanctioned_names(module), symbols
        ):
            return
        managers = self.sanctioned_names(module)
        yield self.finding(
            node,
            '%s changes GL state that nothing restores if the code after it raises: the '
            'next draw, view or frame inherits it; restore it in a finally, or use a '
            'context manager that does%s'
            % (ast.unparse(node), ' (%s)' % (' or '.join(managers),) if managers else ''),
        )


def _keys(function: str, node: ast.Call) -> frozenset[tuple[str, str]]:
    """What a restore of the change `node` makes may be: a family and, where it matters, what.

    Turning the scissor test off restores a scissor rectangle as well.
    """
    family = _FAMILIES[function]
    if family in _BY_ARGUMENT and node.args:
        return frozenset({(family, _capability(node.args[0]))})
    if family == 'glScissor':
        return frozenset({(family, ''), ('capability', 'GL_SCISSOR_TEST')})
    return frozenset({(family, '')})


def _capability(node: ast.expr) -> str:
    """The capability `node` names, as its constant\'s name wherever it is imported from."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ast.dump(node)


def _enclosing(node: ast.AST, symbols: Symbols) -> list[ast.AST]:
    """The nodes around `node`, innermost first, up to and including its function."""
    chain = list(symbols.ancestors(node))
    return chain[: chain.index(region(node, symbols)) + 1]


def _restored(node: ast.Call, keys: frozenset[tuple[str, str]], symbols: Symbols) -> bool:
    """Whether a `finally` of the function around `node` restores what it changes."""
    child: ast.AST = node
    for ancestor in _enclosing(node, symbols):
        if isinstance(ancestor, ast.Try):
            if _holds(list(ancestor.finalbody), child):
                return True
            if _holds([*ancestor.body, *ancestor.handlers, *ancestor.orelse], child) and _restores(
                ancestor, keys, symbols
            ):
                return True
        for block in _BLOCKS:
            statements = getattr(ancestor, block, None)
            if isinstance(statements, list) and child in statements:
                later = statements[statements.index(child) + 1 :]
                if any(
                    isinstance(statement, ast.Try) and _restores(statement, keys, symbols)
                    for statement in later
                ):
                    return True
        child = ancestor
    return False


def _holds(statements: list[ast.AST], child: ast.AST) -> bool:
    """Whether `child` is one of `statements`."""
    return any(statement is child for statement in statements)


def _restores(statement: ast.Try, keys: frozenset[tuple[str, str]], symbols: Symbols) -> bool:
    """Whether the `finally` of `statement` makes a change that matches one of `keys`."""
    for final in statement.finalbody:
        for inner in ast.walk(final):
            if isinstance(inner, ast.Call):
                function = gl_function(inner, symbols)
                if function in _FAMILIES and _keys(function, inner) & keys:
                    return True
    return False


def _managed(node: ast.Call, managers: tuple[str, ...], symbols: Symbols) -> bool:
    """Whether `node` is inside a `with` of a sanctioned state manager, in its function."""
    return any(
        isinstance(ancestor, ast.With | ast.AsyncWith)
        and any(
            isinstance(item.context_expr, ast.Call)
            and symbols.qualified_name(item.context_expr.func) in managers
            for item in ancestor.items
        )
        for ancestor in _enclosing(node, symbols)
    )
