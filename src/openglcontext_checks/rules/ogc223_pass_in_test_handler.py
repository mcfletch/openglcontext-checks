"""OGC223: `pass` in a test's exception handler."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .testfunctions import is_test_function

if TYPE_CHECKING:
    from ..engine import Module


class PassInTestHandler(Rule):
    """An `except` handler in a test whose body does nothing.

    A test that catches an exception and does nothing with it passes whether
    or not the exception happened, and whether or not it was the one the test
    was written about. The error the code under test raised is gone, and so is
    the test's ability to report it.

    Reported, in modules in the `test` scope: an `except` handler, anywhere
    inside a test function (named as pytest collects one), whose body is only
    `pass` or `...`.

    Use instead: no handler, so the exception fails the test;
    `pytest.raises` where raising is what the test is about; or an assertion
    in the handler on what was caught.
    """

    code = 'OGC223'
    name = 'pass in a test handler'
    scope = 'test'
    nodes = (ast.ExceptHandler,)

    VALID = (
        snippet("""
            import pytest

            def test_rejects_a_missing_key():
                with pytest.raises(KeyError):
                    lookup('missing')
        """),
        snippet("""
            def remove_scratch(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        """),
        snippet("""
            def test_reports_the_driver():
                try:
                    run()
                except RuntimeError as error:
                    assert 'driver' in str(error)
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                def test_teardown():
                    try:
                        close()
                    except Exception:
                        pass
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                class TestLoader:
                    def test_loads(self):
                        for name in NAMES:
                            try:
                                load(name)
                            except (KeyError, IndexError):
                                ...
                        assert True
            """),
            (6,),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.ExceptHandler)
        if not all(_does_nothing(statement) for statement in node.body):
            return
        symbols = module.symbols
        test = next(
            (
                ancestor
                for ancestor in symbols.ancestors(node)
                if isinstance(ancestor, ast.FunctionDef | ast.AsyncFunctionDef)
                and is_test_function(ancestor, symbols)
            ),
            None,
        )
        if test is None:
            return
        yield self.finding(
            node,
            'except with only pass in %s: the error is dropped and the test passes; let it '
            'fail the test, use pytest.raises, or assert on what was caught' % (test.name,),
        )


def _does_nothing(statement: ast.stmt) -> bool:
    """Whether `statement` is `pass` or `...`."""
    if isinstance(statement, ast.Pass):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )
