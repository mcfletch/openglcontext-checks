"""OGC222: a test with no assertion."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from ..symbols import LOCAL
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
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


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
    `verify`, or is `fail`; or a call to a helper defined in the same module
    whose body has one of these, followed through the helpers it calls in
    turn. A helper is a module-level function called by a name bound to it at
    module level, or a method called on the test's own `self`, found in the
    test's class or a base class defined in the module. Nested blocks count;
    functions, lambdas and classes defined inside the test do not, since
    defining a function does not run it. A parametrised test is judged the
    same way.

    Use instead: assert on what the code produced; `pytest.raises` where the
    point is that it raises. A helper that asserts from another module is
    named for it (`check_image`, `assert_renders`), which is how the rule
    sees it.
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
        snippet("""
            def _same(found, wanted):
                for one, other in zip(found, wanted):
                    _close(one, other)

            def _close(one, other):
                assert abs(one - other) < 1e-6

            class Base:
                def _is_matrix(self, value):
                    assert value.shape == (4, 4)

            class TestLights(Base):
                def test_the_values_are_the_ones_written(self):
                    _same(read(), WRITTEN)

                def test_each_light_has_a_matrix(self):
                    self._is_matrix(light().modelMatrix())
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
        Invalid(
            snippet("""
                def _close(one, other):
                    assert one == other

                def _render(scene):
                    _render(scene.child)

                class TestScene:
                    def _load(self, name):
                        return open(name)

                    def test_through_helpers_that_do_not_assert(self, _close):
                        _render(self._load('scene.wrl'))
                        _close(1, 1)
                        other._close(1, 1)
            """),
            (11,),
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


def _asserts(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    symbols: Symbols,
    followed: set[ast.AST] | None = None,
) -> bool:
    """Whether the body of `function`, less nested definitions, asserts anything.

    A call to a helper defined in the module counts when the helper's body
    asserts; `followed` holds the functions already looked at, so a helper
    that calls itself is read once.
    """
    followed = set() if followed is None else followed
    followed.add(function)
    stack: list[ast.AST] = [
        statement for statement in function.body if not isinstance(statement, _DEFINITIONS)
    ]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assert) or (isinstance(node, ast.Raise) and node.exc):
            return True
        if isinstance(node, ast.Call):
            if _is_asserting_call(node, symbols):
                return True
            helper = _helper(node, symbols)
            if (
                helper is not None
                and helper not in followed
                and _asserts(helper, symbols, followed)
            ):
                return True
        stack.extend(
            child for child in ast.iter_child_nodes(node) if not isinstance(child, _DEFINITIONS)
        )
    return False


def _helper(call: ast.Call, symbols: Symbols) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The function defined in this module that `call` runs, where the syntax says which.

    A name bound at module level by a `def` there, or `self.name` inside a
    method, looked up in the method's class and its bases defined in the
    module.
    """
    target = call.func
    if isinstance(target, ast.Name):
        scope = symbols.binding_scope(target)
        if isinstance(scope, ast.Module) and symbols.lookup(target).kind == LOCAL:
            found = _defined(scope.body, target.id)
            return found if isinstance(found, _FUNCTIONS) else None
        return None
    if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
        return None
    method = symbols.enclosing_function(call)
    if not isinstance(method, _FUNCTIONS) or not method.args.args:
        return None
    owner = symbols.parent(method)
    if (
        not isinstance(owner, ast.ClassDef)
        or method.args.args[0].arg != target.value.id
        or symbols.binding_scope(target.value) is not method
    ):
        return None
    return _method(owner, target.attr, symbols, set())


def _method(
    owner: ast.ClassDef, name: str, symbols: Symbols, searched: set[ast.ClassDef]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The method `name` of `owner` or of a base class defined in the module."""
    searched.add(owner)
    found = _defined(owner.body, name)
    if found is not None:
        return found if isinstance(found, _FUNCTIONS) else None
    for base in owner.bases:
        if not isinstance(base, ast.Name):
            continue
        scope = symbols.binding_scope(base)
        if not isinstance(scope, ast.Module) or symbols.lookup(base).kind != LOCAL:
            continue
        parent = _defined(scope.body, base.id)
        if isinstance(parent, ast.ClassDef) and parent not in searched:
            method = _method(parent, name, symbols, searched)
            if method is not None:
                return method
    return None


def _defined(body: list[ast.stmt], name: str) -> ast.stmt | None:
    """The last statement of `body` that binds `name`, or None.

    A `def` or `class` of that name is the definition itself; any other
    statement binding it (an assignment, an import, a definition inside an
    `if` or a `try`) is returned as it is, and is no helper the syntax can
    follow.
    """
    found: ast.stmt | None = None
    for statement in body:
        if isinstance(statement, (*_FUNCTIONS, ast.ClassDef)):
            if statement.name == name:
                found = statement
        elif any(_binds(node, name) for node in ast.walk(statement)):
            found = statement
    return found


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


def _binds(node: ast.AST, name: str) -> bool:
    """Whether `node` binds `name`: an assignment, an import or a definition."""
    if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
        return node.name == name
    if isinstance(node, ast.Name):
        return node.id == name and not isinstance(node.ctx, ast.Load)
    if isinstance(node, ast.alias):
        return (node.asname or node.name).split('.')[0] == name
    return False
