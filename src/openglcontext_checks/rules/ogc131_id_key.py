"""OGC131: `id()` as a key."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from ..symbols import BUILTIN
from .base import Invalid, Rule, snippet

if TYPE_CHECKING:
    from ..engine import Module
    from ..symbols import Symbols

#: Methods whose first argument is a key or a member.
_KEYED_METHODS = frozenset({'get', 'setdefault', 'pop', 'add', 'discard', 'remove'})
_DISPLAYS = (ast.Tuple, ast.List, ast.Set)


class IdAsKey(Rule):
    """`id(x)` used as a key, where the same statement does not hold `x`.

    An id is an address, and CPython hands it to the next object allocated
    there as soon as `x` is collected. A table keyed on `id(x)` then answers a
    new object with the old object's entry: a cache returns another mesh's
    fitted bounds, a registry treats a new context as one it has already set
    up. The shapes flagged are `id(x)` (alone or in a tuple) as a subscript,
    a dict display or comprehension key, a set member, the left side of `in`,
    the first argument of `get`, `setdefault`, `pop`, `add`, `discard` or
    `remove`, and a value assigned to an attribute.

    The statement is not flagged when it also holds `x` itself: as the
    assigned value or inside it, as a dict display's value, as
    `setdefault`'s default, or through `weakref.ref(x)`. An entry that holds
    its object keeps the id from being reused while the entry exists.

    Use instead: key on the object (`WeakKeyDictionary` where the table should
    not keep it alive), or hold the object in the entry and compare it on
    lookup. Comparing two ids in one expression, and printing one, are not
    keys and are not flagged.
    """

    code = 'OGC131'
    name = 'id() as a key'
    nodes = (ast.Call,)

    VALID = (
        snippet("""
            cache[id(mesh)] = (mesh, fitted)
        """),
        snippet("""
            self._entries[id(node)] = node
        """),
        snippet("""
            by_id = {id(item): item for item in items}
        """),
        snippet("""
            owners = {id(context): context}
        """),
        snippet("""
            import weakref
            self._seen[id(obj)] = weakref.ref(obj)
        """),
        snippet("""
            table.setdefault(id(node), node)
        """),
        snippet("""
            log.debug('node %x drawn', id(node))
            if id(a) == id(b):
                pass
            same = id(a) in (id(b), id(c))
        """),
        snippet("""
            def lookup(id, table, node):
                return table[id(node)]
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                _FITS = {}
                def fit(positions):
                    if id(positions) in _FITS:
                        return _FITS[id(positions)]
                    _FITS[id(positions)] = fitted = compute(positions)
                    return fitted
            """),
            (3, 4, 5),
        ),
        Invalid(snippet('value = cache.get(id(node))\n'), (1,)),
        Invalid(snippet('cache.setdefault(id(node), []).append(1)\n'), (1,)),
        Invalid(snippet('cache.pop(id(node), None)\n'), (1,)),
        Invalid(snippet('table = {id(node): 1}\n'), (1,)),
        Invalid(snippet('seen = {id(node)}\nseen.add(id(other))\n'), (1, 2)),
        Invalid(snippet('self.owner = id(context)\n'), (1,)),
        Invalid(snippet('cache[id(a), id(b)] = combine(a, b)\n'), (1, 1)),
        Invalid(snippet('self._key: tuple[int, int] = (id(view), 2)\n'), (1,)),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        if not (
            isinstance(node.func, ast.Name)
            and len(node.args) == 1
            and not node.keywords
            and symbols.lookup(node.func).kind == BUILTIN
            and node.func.id == 'id'
        ):
            return
        if not _used_as_key(node, symbols):
            return
        held = node.args[0]
        statement = next(
            ancestor for ancestor in symbols.ancestors(node) if isinstance(ancestor, ast.stmt)
        )
        if _holds(statement, ast.dump(held), symbols):
            return
        text = ast.unparse(held)
        if len(text) > 40:
            text = text[:37] + '...'
        yield self.finding(
            node,
            'id(%s) as a key: the id is reused once the object is collected, so the entry '
            'can answer a different object; key on the object (a WeakKeyDictionary) or hold '
            'it in the entry' % (text,),
        )


def _used_as_key(node: ast.Call, symbols: Symbols) -> bool:
    """Whether `node`, alone or in a tuple, is used where a key or member goes."""
    key: ast.AST = node
    parent = symbols.parent(node)
    while isinstance(parent, ast.Tuple):
        key, parent = parent, symbols.parent(parent)
    if isinstance(parent, ast.Subscript):
        return key is parent.slice
    if isinstance(parent, ast.Dict):
        return any(key is candidate for candidate in parent.keys)
    if isinstance(parent, ast.DictComp):
        return key is parent.key
    if isinstance(parent, ast.Set | ast.SetComp):
        return True
    if isinstance(parent, ast.Compare):
        return (
            key is parent.left
            and isinstance(parent.ops[0], ast.In | ast.NotIn)
            and not isinstance(parent.comparators[0], _DISPLAYS)
        )
    if isinstance(parent, ast.Call):
        return (
            isinstance(parent.func, ast.Attribute)
            and parent.func.attr in _KEYED_METHODS
            and bool(parent.args)
            and key is parent.args[0]
        )
    if isinstance(parent, ast.Assign):
        return len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Attribute)
    if isinstance(parent, ast.AnnAssign):
        return isinstance(parent.target, ast.Attribute)
    return False


def _holds(statement: ast.stmt, held: str, symbols: Symbols) -> bool:
    """Whether `statement` stores the expression whose dump is `held`."""
    roots: list[ast.expr] = []
    if isinstance(statement, ast.Assign | ast.AnnAssign | ast.AugAssign) and statement.value:
        roots.append(statement.value)
    for node in _own_expressions(statement):
        if isinstance(node, ast.Dict):
            roots.extend(node.values)
        elif isinstance(node, ast.DictComp):
            roots.append(node.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'setdefault'
        ):
            roots.extend(node.args[1:])
    while roots:
        value = roots.pop()
        if ast.dump(value) == held:
            return True
        if isinstance(value, _DISPLAYS):
            roots.extend(value.elts)
        elif isinstance(value, ast.Starred):
            roots.append(value.value)
        elif (
            isinstance(value, ast.Call)
            and value.args
            and symbols.qualified_name(value.func) == 'weakref.ref'
        ):
            roots.append(value.args[0])
    return False


def _own_expressions(statement: ast.stmt) -> Iterator[ast.AST]:
    """The nodes of `statement` itself, not of the statements nested in it."""
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(
            child for child in ast.iter_child_nodes(node) if not isinstance(child, ast.stmt)
        )
