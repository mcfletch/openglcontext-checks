"""OGC221: a skip inside an `except`, in a test."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet

if TYPE_CHECKING:
    from ..engine import Module

_SKIPS = frozenset({'pytest.skip', 'pytest.xfail', 'pytest.importorskip'})
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


class SkipInExcept(Rule):
    """`pytest.skip`, `pytest.xfail` or `pytest.importorskip` in an `except` body.

    A test that catches an exception and skips turns the failure it exists to
    detect into a skip: a crash in the renderer, a module that no longer
    imports, a driver error, each reported as "skipped" in a run that reads
    green. A handler catching `ImportError` hides a module broken by a typo as
    readily as one that is not installed.

    Reported, in modules in the `test` scope: a call resolving to
    `pytest.skip`, `pytest.xfail` or `pytest.importorskip`, through any import
    form, in the body of an `except` handler, at any depth up to the nearest
    function.

    Use instead: `pytest.importorskip('module')` on its own for an optional
    dependency; a check that says whether the capability is there (a display,
    a driver extension) before the code under test runs, with the skip on
    that check; and otherwise, no handler, so the exception fails the test.
    """

    code = 'OGC221'
    name = 'skip inside an except'
    scope = 'test'
    nodes = (ast.Call,)

    VALID = (
        snippet("""
            import pytest

            def test_needs_numpy():
                numpy = pytest.importorskip('numpy')
                assert numpy.zeros(1).shape == (1,)
        """),
        snippet("""
            import sys
            import pytest

            def test_windows_only():
                if sys.platform != 'win32':
                    pytest.skip('the WGL backend is Windows only')
                assert open_pbuffer()
        """),
        snippet("""
            import pytest

            def test_lookup():
                try:
                    value = lookup('key')
                except KeyError as error:
                    pytest.fail('lookup refused a present key: %s' % error)
                assert value
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                import pytest

                def test_render():
                    try:
                        image = render()
                    except Exception as error:
                        pytest.skip('render failed: %s' % error)
                    assert image
            """),
            (7,),
        ),
        Invalid(
            snippet("""
                from pytest import importorskip, xfail

                def test_decode():
                    try:
                        import draco
                    except ImportError:
                        importorskip('draco')
                    try:
                        decode()
                    except RuntimeError:
                        if draco:
                            xfail('driver bug')
            """),
            (7, 12),
        ),
        Invalid(
            snippet("""
                import pytest as pt

                try:
                    import glfw
                except ImportError:
                    pt.skip('no glfw', allow_module_level=True)
            """),
            (6,),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        qualified = symbols.qualified_name(node.func)
        if qualified not in _SKIPS:
            return
        child: ast.AST = node
        for ancestor in symbols.ancestors(node):
            if isinstance(ancestor, _FUNCTIONS):
                return
            if isinstance(ancestor, ast.ExceptHandler) and any(
                child is statement for statement in ancestor.body
            ):
                yield self.finding(
                    node,
                    '%s() in an except handler: the failure it catches is reported as a skip; '
                    'use pytest.importorskip for an optional module, or let the exception '
                    'fail the test' % (qualified,),
                )
                return
            child = ancestor
