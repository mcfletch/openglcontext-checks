"""OGC222: a test with no assertion."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .testfunctions import is_test_function

if TYPE_CHECKING:
    from ..engine import Module
    from ..symbols import Symbols

_ASSERTING_CALLS = frozenset(
    {'pytest.raises', 'pytest.warns', 'pytest.fail', 'pytest.deprecated_call'}
)
_ASSERTING_PREFIXES = ('assert', 'check', 'expect', 'verify')
_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class TestWithoutAssertion(Rule):
    """A test function whose body can only fail by raising.

    A test with no assertion passes whatever the code returns: a renderer
    that draws nothing, a loader that returns an empty scene, a function
    that answers the wrong number. It fails only if something raises, which
    is a much weaker claim than the test's name usually makes.

    Reported, in modules in the `test` scope: a function named as pytest
    collects a test (starting with `test`), at module level or as a method of
    a module-level class, whose body has none of: an `assert` statement; a
    `raise`; a call to `pytest.raises`, `pytest.warns`, `pytest.fail` or
    `pytest.deprecated_call`; a call to a function or method whose name
    (leading underscores aside) starts with `assert`, `check`, `expect` or
    `verify`, or is `fail`. Nested blocks count; functions, lambdas and
    classes defined inside the test do not, since defining a function does
    not run it. A parametrised test is judged the same way.

    Use instead: assert on what the code produced; `pytest.raises` where the
    point is that it raises. A helper that asserts is named for it
    (`check_image`, `assert_renders`), which is how the rule sees it.
    """

    __test__ = False  # the class name starts with Test, and pytest should not collect it

    code = 'OGC222'
    name = 'test with no assertion'
    scope = 'test'
    nodes = (ast.FunctionDef, ast.AsyncFunctionDef)

    VALID = (
        snippet("""
            def test_sum():
                assert sum([1, 2]) == 3
        """),
        snippet("""
            import pytest

            def test_rejects_a_negative_size():
                with pytest.raises(ValueError):
                    parse(-1)
        """),
        snippet("""
            import unittest

            class TestLoader(unittest.TestCase):
                def test_loads(self):
                    self.assertEqual(load('a'), 1)
        """),
        snippet("""
            def test_matches_the_reference(image):
                for case in CASES:
                    if case.enabled:
                        check_image(image, case.reference)

            def helper():
                render()
        """),
        snippet("""
            import pytest

            @pytest.mark.parametrize('n', [1, 2])
            async def test_parametrised(n):
                if n < 0:
                    raise AssertionError(n)
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                def test_renders():
                    render()
            """),
            (1,),
        ),
        Invalid(
            snippet("""
                class TestScene:
                    def test_loads(self):
                        load('scene.wrl')
            """),
            (2,),
        ),
        Invalid(
            snippet("""
                import pytest

                @pytest.mark.parametrize('n', [1, 2])
                def test_each(n):
                    compute(n)
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                def test_asserts_only_in_a_helper_it_never_calls():
                    def helper():
                        assert True
                    lambda: check(1)
            """),
            (1,),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        symbols = module.symbols
        if not is_test_function(node, symbols) or _asserts(node, symbols):
            return
        yield self.finding(
            node,
            '%s has no assertion: it passes whatever the code does, unless something raises; '
            'assert on the result, or use pytest.raises' % (node.name,),
        )


def _asserts(function: ast.FunctionDef | ast.AsyncFunctionDef, symbols: Symbols) -> bool:
    """Whether the body of `function`, less nested definitions, asserts anything."""
    stack: list[ast.AST] = [
        statement for statement in function.body if not isinstance(statement, _DEFINITIONS)
    ]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assert) or (isinstance(node, ast.Raise) and node.exc):
            return True
        if isinstance(node, ast.Call) and _is_asserting_call(node, symbols):
            return True
        stack.extend(
            child for child in ast.iter_child_nodes(node) if not isinstance(child, _DEFINITIONS)
        )
    return False


def _is_asserting_call(call: ast.Call, symbols: Symbols) -> bool:
    if symbols.qualified_name(call.func) in _ASSERTING_CALLS:
        return True
    if isinstance(call.func, ast.Name):
        name = call.func.id
    elif isinstance(call.func, ast.Attribute):
        name = call.func.attr
    else:
        return False
    name = name.lstrip('_').lower()
    return name == 'fail' or name.startswith(_ASSERTING_PREFIXES)
