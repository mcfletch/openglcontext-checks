"""What each name in a module is bound to, and where each node sits.

One pass over the syntax tree records, for every node, its parent and the
scope it is evaluated in, and for every scope, the names bound in it and the
modules star-imported into it. A rule then asks what a name or a dotted
attribute refers to: `GL.glFinish` after `from OpenGL import GL` is
`OpenGL.GL.glFinish`.

Scopes are the module, each function, lambda and class. A function's
decorators, defaults and annotations are evaluated in the scope around it, and
its parameters are bound inside it. A class body is not visible from the
functions defined in it, as in Python. Comprehensions are not separate scopes
here: a name bound in one counts as bound in the scope around it.

An import binds the qualified name it imports. Any other binding (assignment,
parameter, `for`, `with`, `except`, `match`, `def`, `class`, `del`) makes the
name local. Where one scope has both, the import wins, which reads the
`try: from x import y` / `except ImportError: y = None` pattern as the import.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
from collections.abc import Iterator

IMPORTED = 'imported'
LOCAL = 'local'
BUILTIN = 'builtin'
UNBOUND = 'unbound'

_BUILTINS = frozenset(dir(builtins))
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_Scope = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef


@dataclasses.dataclass(frozen=True)
class Binding:
    """What a name refers to at one place in a module."""

    kind: str
    #: The dotted name it was imported as, or `builtins.<name>`; None otherwise.
    qualified: str | None = None


class Symbols:
    """Parents, scopes and bindings for one module's syntax tree."""

    def __init__(self, tree: ast.Module) -> None:
        self._parents: dict[ast.AST, ast.AST] = {}
        self._scopes: dict[ast.AST, _Scope] = {}
        self._outer: dict[_Scope, _Scope | None] = {tree: None}
        self._bound: dict[_Scope, dict[str, str | None]] = {tree: {}}
        self._stars: dict[_Scope, list[str]] = {tree: []}
        self._build(tree)

    def parent(self, node: ast.AST) -> ast.AST | None:
        """The node `node` is a child of; None for the module."""
        return self._parents.get(node)

    def ancestors(self, node: ast.AST) -> Iterator[ast.AST]:
        """Each node enclosing `node`, innermost first, ending at the module."""
        current = self._parents.get(node)
        while current is not None:
            yield current
            current = self._parents.get(current)

    def scope_of(self, node: ast.AST) -> _Scope:
        """The scope `node` is evaluated in."""
        return self._scopes[node]

    def lookup(self, node: ast.Name) -> Binding:
        """What the name `node` refers to where it appears."""
        name = node.id
        scope: _Scope | None = self._scopes[node]
        innermost = True
        while scope is not None:
            if innermost or not isinstance(scope, ast.ClassDef):
                bound = self._bound[scope]
                if name in bound:
                    qualified = bound[name]
                    if qualified is None:
                        return Binding(LOCAL)
                    return Binding(IMPORTED, qualified)
            scope = self._outer[scope]
            innermost = False
        if name in _BUILTINS:
            return Binding(BUILTIN, 'builtins.' + name)
        return Binding(UNBOUND)

    def qualified_name(self, node: ast.expr) -> str | None:
        """The dotted name `node` refers to, through imports; None if unknown.

        A name that is imported or builtin, or an attribute chain on one,
        has a qualified name. Anything else does not.
        """
        if isinstance(node, ast.Name):
            return self.lookup(node).qualified
        if isinstance(node, ast.Attribute):
            base = self.qualified_name(node.value)
            if base is not None:
                return '%s.%s' % (base, node.attr)
        return None

    def star_modules(self, node: ast.AST) -> tuple[str, ...]:
        """The modules star-imported into the scopes `node` can see, innermost first."""
        found: list[str] = []
        scope: _Scope | None = self._scopes[node]
        innermost = True
        while scope is not None:
            if innermost or not isinstance(scope, ast.ClassDef):
                found.extend(self._stars[scope])
            scope = self._outer[scope]
            innermost = False
        return tuple(found)

    def _bind(self, scope: _Scope, name: str, qualified: str | None = None) -> None:
        bound = self._bound[scope]
        if qualified is not None or name not in bound:
            bound[name] = qualified

    def _open(self, scope: _Scope, outer: _Scope) -> None:
        self._outer[scope] = outer
        self._bound[scope] = {}
        self._stars[scope] = []

    def _build(self, tree: ast.Module) -> None:
        # Iterative rather than recursive: a long chain of binary operators is
        # nested as deep as it is long.
        stack: list[tuple[ast.AST, _Scope]] = [(tree, tree)]
        while stack:
            node, scope = stack.pop()
            self._scopes[node] = scope
            inner: _Scope | None = None
            if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
                inner = node
                self._open(inner, scope)
                if not isinstance(node, ast.Lambda):
                    self._bind(scope, node.name)
                if isinstance(node, _FUNCTIONS):
                    arguments = node.args
                    for argument in (
                        *arguments.posonlyargs,
                        *arguments.args,
                        *arguments.kwonlyargs,
                        arguments.vararg,
                        arguments.kwarg,
                    ):
                        if argument is not None:
                            self._bind(inner, argument.arg)
            else:
                self._record_binding(node, scope)
            for field, value in ast.iter_fields(node):
                child_scope = inner if inner is not None and field == 'body' else scope
                for child in value if isinstance(value, list) else [value]:
                    if isinstance(child, ast.AST):
                        self._parents[child] = node
                        stack.append((child, child_scope))

    def _record_binding(self, node: ast.AST, scope: _Scope) -> None:
        if isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load):
                self._bind(scope, node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self._bind(scope, alias.asname, alias.name)
                else:
                    top = alias.name.split('.')[0]
                    self._bind(scope, top, top)
        elif isinstance(node, ast.ImportFrom):
            module = '.' * node.level + (node.module or '')
            for alias in node.names:
                if alias.name == '*':
                    self._stars[scope].append(module)
                    continue
                joiner = '' if module.endswith('.') else '.'
                self._bind(
                    scope, alias.asname or alias.name, '%s%s%s' % (module, joiner, alias.name)
                )
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar):
            if node.name:
                self._bind(scope, node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            self._bind(scope, node.rest)
