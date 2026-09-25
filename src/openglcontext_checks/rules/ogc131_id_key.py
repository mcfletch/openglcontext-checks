"""OGC131: `id()` as a key."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from ..symbols import BUILTIN, LOCAL
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

    Three other uses are not flagged:

    - A table that exists for one call: a plain name the function binds only
      to containers it makes there (a display, a comprehension, `set()`,
      `dict()`, `collections.defaultdict(...)`), and uses only in place: its
      methods called, subscripted, compared, iterated, tested for truth or
      measured with `len`. Not a parameter, not global or nonlocal, never
      passed to a call, returned, stored elsewhere or read from a nested
      function. It is dropped when the call returns, while the objects it was
      keyed on are the ones the call is walking; a visited-set is the usual
      case.
    - A set or dict display that is compared or measured with `len` and
      never stored, as in `len({id(v) for v in views}) == len(views)`.
    - A lookup whose entry is compared by identity with the object: the
      result assigned to a name, and the function comparing a part of it
      (`entry[0] is x`, `entry.path is not x`) with `x`.

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
        snippet("""
            def shapes(root):
                found = []
                stack = [root]
                seen: set[int] = set()
                while stack:
                    node = stack.pop()
                    if id(node) in seen:
                        continue
                    seen.add(id(node))
                    if len(seen) > 1 and seen:
                        found.append(node)
                    stack.extend(node.children)
                return found
        """),
        snippet("""
            def by_material(parts):
                merged = {}
                for part in parts:
                    merged.setdefault((part.group, id(part.material)), []).append(part)
                return [group for group in merged.values()]
        """),
        snippet("""
            def chunks(members):
                chunk, slot = [], {}
                for member in members:
                    if id(member.material) not in slot:
                        chunk, slot = [], {}
                        slot[id(member.material)] = len(chunk)
                    chunk.append(slot[id(member.material)])
                return chunk
        """),
        snippet("""
            def shared(frames, found):
                drawn = set()
                drawn |= {(id(frame), path) for frame in frames for path in found}
                return [frame for frame in frames if (id(frame), 1) not in drawn]
        """),
        snippet("""
            unique = len({id(view) for view in views}) == len(views)
            assert {id(a) for a in left} == {id(b) for b in right}
        """),
        snippet("""
            def box(self, bvolume):
                entry = self._boxes.get(id(bvolume))
                if entry is None or entry[0] is not bvolume:
                    entry = self._boxes[id(bvolume)] = (bvolume, measure(bvolume))
                return entry[1]
        """),
        snippet("""
            def zones(self, path):
                held = self._objects.get(id(path))
                if held is None or held.path is not path:
                    self.classify(path)
                    held = self._objects[id(path)]
                return held
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
        Invalid(
            snippet("""
                def weights(zones, values):
                    return {id(zone): value for zone, value in zip(zones, values)}
            """),
            (2,),
        ),
        Invalid(
            snippet("""
                def weights(zones):
                    found = {}
                    for zone in zones:
                        found[id(zone)] = zone.weight
                    return found
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                def mark(self, nodes):
                    seen = self.seen = set()
                    for node in nodes:
                        seen.add(id(node))
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                def mark(self, nodes):
                    seen = self._seen
                    for node in nodes:
                        seen.add(id(node))
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                def mark(self, nodes):
                    seen = set(self._ids)
                    return [node for node in nodes if id(node) not in seen]
            """),
            (3,),
        ),
        Invalid(
            snippet("""
                def mark(nodes, seen):
                    for node in nodes:
                        seen.add(id(node))
            """),
            (3,),
        ),
        Invalid(
            snippet("""
                def mark(nodes):
                    seen = set()
                    for node in nodes:
                        seen.add(id(node))
                    return lambda node: id(node) in seen
            """),
            (4, 5),
        ),
        Invalid(
            snippet("""
                def mark(nodes, into):
                    seen = set()
                    for node in nodes:
                        seen.add(id(node))
                    into.record(seen)
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                def mark(nodes):
                    global SEEN
                    SEEN = set()
                    for node in nodes:
                        SEEN.add(id(node))
            """),
            (5,),
        ),
        Invalid(
            snippet("""
                def mark(nodes):
                    seen = {}
                    for seen in nodes:
                        seen[id(seen)] = 1
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                def zones(self, path):
                    held = self._objects.get(id(path))
                    if held is None or held.matrix is not path.matrix:
                        held = self.classify(path)
                    return held
            """),
            (2,),
        ),
        Invalid(snippet('stored = [{id(node): node.name}]\n'), (1,)),
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
        dumped = ast.dump(held)
        statement = next(
            ancestor for ancestor in symbols.ancestors(node) if isinstance(ancestor, ast.stmt)
        )
        if _holds(statement, dumped, symbols):
            return
        use, table = _container(node, symbols)
        if isinstance(table, _TABLES):
            if _temporary(table, symbols):
                return
            table = _bound_to(table, symbols) or table
        if isinstance(table, ast.Name) and _call_local(table, symbols):
            return
        if _compared_on_lookup(use, dumped, symbols):
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


def _container(node: ast.Call, symbols: Symbols) -> tuple[ast.AST, ast.AST]:
    """The expression `node` is a key in, and the table that expression reads or writes.

    For a display or comprehension, and for an attribute store, the two are
    the same node.
    """
    parent = symbols.parent(node)
    while isinstance(parent, ast.Tuple):
        parent = symbols.parent(parent)
    if isinstance(parent, ast.Subscript):
        return parent, parent.value
    if isinstance(parent, ast.Call):
        assert isinstance(parent.func, ast.Attribute)
        return parent, parent.func.value
    if isinstance(parent, ast.Compare):
        return parent, parent.comparators[0]
    assert parent is not None
    return parent, parent


def _temporary(table: ast.AST, symbols: Symbols) -> bool:
    """Whether a display is compared or measured and then dropped, never stored."""
    parent = symbols.parent(table)
    if isinstance(parent, ast.Compare):
        return True
    return _builtin_call(parent, symbols, 'len')


def _builtin_call(node: ast.AST | None, symbols: Symbols, *names: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in names
        and symbols.lookup(node.func).kind == BUILTIN
    )


def _bound_to(table: ast.AST, symbols: Symbols) -> ast.Name | None:
    """The plain name a display is assigned to, alone or unpacked from a tuple."""
    parent = symbols.parent(table)
    target: ast.expr | None = None
    if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
        target = parent.targets[0]
    elif isinstance(parent, ast.AnnAssign | ast.AugAssign):
        target = parent.target
    elif isinstance(parent, _DISPLAYS):
        assign = symbols.parent(parent)
        if (
            isinstance(assign, ast.Assign)
            and len(assign.targets) == 1
            and isinstance(assign.targets[0], _DISPLAYS)
            and len(assign.targets[0].elts) == len(parent.elts)
        ):
            index = next(i for i, elt in enumerate(parent.elts) if elt is table)
            target = assign.targets[0].elts[index]
    return target if isinstance(target, ast.Name) else None


def _call_local(name: ast.Name, symbols: Symbols) -> bool:
    """Whether the table `name` exists only for one call of the function binding it.

    Every binding of the name in the function makes a new, empty or freshly
    filled container, and every other use of it reads or fills it in place:
    it is not a parameter, not global or nonlocal, not passed to a call,
    returned, stored elsewhere or seen from a nested function. The table is
    dropped when the call returns, while the objects it was keyed on are the
    ones the call is walking.
    """
    function = symbols.enclosing_function(name)
    if function is None or isinstance(function, ast.Lambda):
        return False
    if symbols.lookup(name).kind != LOCAL:
        return False
    arguments = function.args
    parameters = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        arguments.vararg,
        arguments.kwarg,
    ]
    if any(parameter is not None and parameter.arg == name.id for parameter in parameters):
        return False
    bound = False
    for node in ast.walk(function):
        if isinstance(node, ast.Global | ast.Nonlocal) and name.id in node.names:
            return False
        if not isinstance(node, ast.Name) or node.id != name.id:
            continue
        if symbols.scope_of(node) is not function:
            return False
        if isinstance(node.ctx, ast.Store):
            if not _fresh_binding(node, symbols):
                return False
            bound = True
        elif isinstance(node.ctx, ast.Load) and not _stays(node, symbols):
            return False
    return bound


#: What makes a new container.
_FACTORIES = frozenset(
    {
        'builtins.set',
        'builtins.frozenset',
        'builtins.dict',
        'builtins.list',
        'builtins.tuple',
        'collections.defaultdict',
        'collections.OrderedDict',
        'collections.Counter',
    }
)
_TABLES = (ast.Dict, ast.DictComp, ast.Set, ast.SetComp)
_MADE_HERE = (*_DISPLAYS, *_TABLES, ast.ListComp, ast.GeneratorExp)


def _fresh_binding(node: ast.Name, symbols: Symbols) -> bool:
    """Whether the store `node` binds the name to a container made there."""
    parent = symbols.parent(node)
    if isinstance(parent, ast.AugAssign):
        return True
    if isinstance(parent, ast.AnnAssign):
        return parent.value is None or _fresh(parent.value, symbols)
    if isinstance(parent, ast.Assign):
        return len(parent.targets) == 1 and _fresh(parent.value, symbols)
    if isinstance(parent, _DISPLAYS):
        assign = symbols.parent(parent)
        if (
            isinstance(assign, ast.Assign)
            and assign.targets == [parent]
            and isinstance(assign.value, _DISPLAYS)
            and len(assign.value.elts) == len(parent.elts)
        ):
            index = next(i for i, elt in enumerate(parent.elts) if elt is node)
            return _fresh(assign.value.elts[index], symbols)
    return False


def _fresh(value: ast.expr, symbols: Symbols) -> bool:
    """Whether `value` is a container made by this expression, holding nothing older."""
    if isinstance(value, _MADE_HERE):
        return True
    if not isinstance(value, ast.Call) or value.keywords:
        return False
    qualified = symbols.qualified_name(value.func)
    if qualified not in _FACTORIES:
        return False
    contents = value.args[1:] if qualified == 'collections.defaultdict' else value.args
    return all(isinstance(argument, _MADE_HERE) for argument in contents)


def _stays(node: ast.Name, symbols: Symbols) -> bool:
    """Whether this use of a table reads or fills it without handing it on."""
    current: ast.AST = node
    parent = symbols.parent(node)
    while isinstance(parent, ast.BoolOp) or (
        isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not)
    ):
        current, parent = parent, symbols.parent(parent)
    if isinstance(parent, ast.If | ast.While | ast.IfExp | ast.Assert):
        return parent.test is current
    if current is not node:
        return False
    if isinstance(parent, ast.Attribute):
        method = symbols.parent(parent)
        return isinstance(method, ast.Call) and method.func is parent and parent.attr != 'copy'
    if isinstance(parent, ast.Subscript):
        return parent.value is node
    if isinstance(parent, ast.Compare):
        return True
    if isinstance(parent, ast.comprehension | ast.For | ast.AsyncFor):
        return parent.iter is node
    return _builtin_call(parent, symbols, 'len', 'bool')


#: The comparisons that test whether an entry is the object's own.
_IDENTITY = (ast.Is, ast.IsNot)


def _compared_on_lookup(use: ast.AST, held: str, symbols: Symbols) -> bool:
    """Whether a lookup's entry is checked to be the keyed object's before use.

    The lookup is assigned to a name, and the function compares a part of
    that entry (`entry[0]`, `entry.path`) by identity with the object.
    """
    if isinstance(use, ast.Subscript):
        if not isinstance(use.ctx, ast.Load):
            return False
    elif not (
        isinstance(use, ast.Call)
        and isinstance(use.func, ast.Attribute)
        and use.func.attr in ('get', 'pop')
    ):
        return False
    assign = symbols.parent(use)
    if not (
        isinstance(assign, ast.Assign)
        and assign.value is use
        and len(assign.targets) == 1
        and isinstance(assign.targets[0], ast.Name)
    ):
        return False
    entry = assign.targets[0].id
    scope: ast.AST = symbols.enclosing_function(use) or list(symbols.ancestors(use))[-1]
    for node in ast.walk(scope):
        if not (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], _IDENTITY)
        ):
            continue
        for part, other in ((node.left, node.comparators[0]), (node.comparators[0], node.left)):
            if (
                isinstance(part, ast.Subscript | ast.Attribute)
                and isinstance(part.value, ast.Name)
                and part.value.id == entry
                and ast.dump(other) == held
            ):
                return True
    return False
