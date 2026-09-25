"""What a path expression is made of, read within the function it is written in.

The file rules ask two questions of the expression a call is handed as a path.
OGC111 asks whether the function built it from a part the source does not fix
(`os.path.join(base, name)` with `name` a parameter), or looked it up in a
table. OGC121 asks which directory it is under: one a staging call or
`tempfile` made, or somewhere a reader will look.

Both follow a local name to what the function assigns it, through every
assignment, and look through the calls that change a path's spelling but not
where it leads (`os.path.abspath`, `str`, `pathlib.Path` of one argument). A
parameter, an attribute and the result of any other call are taken as they
are: where they came from is decided outside the function.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from ..symbols import LOCAL, Symbols

#: The calls that join their arguments into one path.
JOINS = frozenset({'os.path.join', 'posixpath.join', 'ntpath.join'})

#: The path classes, which join their arguments when given more than one.
PATH_CLASSES = frozenset(
    {
        'pathlib.Path',
        'pathlib.PurePath',
        'pathlib.PosixPath',
        'pathlib.PurePosixPath',
        'pathlib.WindowsPath',
        'pathlib.PureWindowsPath',
    }
)

#: The calls whose one argument leads to the same file as their result.
SPELLINGS = frozenset(
    {
        'os.path.abspath',
        'os.path.normpath',
        'os.path.realpath',
        'os.path.expanduser',
        'os.fspath',
        'builtins.str',
    }
)

_Function = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.Module

#: The value `assigned` gives for a parameter the function also reassigns:
#: whatever the caller passed.
PARAMETER: ast.expr = ast.Name('<parameter>', ast.Load())


def region(node: ast.AST, symbols: Symbols) -> _Function:
    """The function `node` is written in, or the module outside any function."""
    function = symbols.enclosing_function(node)
    if function is not None:
        return function
    outermost = [node, *symbols.ancestors(node)][-1]
    assert isinstance(outermost, ast.Module)
    return outermost


def statements_of(function: _Function) -> Iterator[ast.AST]:
    """Every node of `function`'s own body, less the functions and classes in it."""
    stack: list[ast.AST] = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            stack.extend(ast.iter_child_nodes(node))


def assigned(name: ast.Name, symbols: Symbols) -> list[ast.expr] | None:
    """What the function reading `name` assigns to it, when it is local there.

    None when the name is not a local of that function: a parameter that is
    never reassigned, a name of an enclosing scope, an import or a builtin.
    Each value is the expression the name takes: an assignment's value, the
    elements of a literal sequence a `for` loop walks (as a tuple) or else the
    iterable itself, a `with` item's context expression, or the whole value a
    tuple target is unpacked from when it is not a literal of the same length.
    A parameter the function reassigns has `PARAMETER` among its values.
    """
    scope = symbols.binding_scope(name)
    if scope is None or isinstance(scope, ast.ClassDef) or symbols.lookup(name).kind != LOCAL:
        return None
    values: list[ast.expr] = []
    if not isinstance(scope, ast.Module) and name.id in _parameters(scope.args):
        values.append(PARAMETER)
    for node in statements_of(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                values.extend(_bound(target, node.value, name.id))
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr) and node.value is not None:
            values.extend(_bound(node.target, node.value, name.id))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name.id:
                values.append(ast.BinOp(node.target, node.op, node.value))
        elif isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
            values.extend(_bound(node.target, _element(node.iter), name.id))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            values.extend(_bound(node.optional_vars, node.context_expr, name.id))
    if not values or values == [PARAMETER]:
        return None
    return values


def _parameters(arguments: ast.arguments) -> set[str]:
    """The names a function's parameters bind."""
    return {
        argument.arg
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            arguments.vararg,
            arguments.kwarg,
        )
        if argument is not None
    }


def _bound(target: ast.expr, value: ast.expr, wanted: str) -> list[ast.expr]:
    """The values `target` gives the name `wanted` when it is assigned `value`."""
    if isinstance(target, ast.Name):
        return [value] if target.id == wanted else []
    if isinstance(target, ast.Tuple | ast.List):
        found: list[ast.expr] = []
        for index, element in enumerate(target.elts):
            if isinstance(value, ast.Tuple | ast.List) and len(value.elts) == len(target.elts):
                found.extend(_bound(element, value.elts[index], wanted))
            else:
                found.extend(_bound(element, value, wanted))
        return found
    return []


def _element(iterable: ast.expr) -> ast.expr:
    """What a loop over `iterable` binds: one element of a literal sequence, if it is one."""
    if isinstance(iterable, ast.Tuple | ast.List | ast.Set) and iterable.elts:
        return ast.Tuple(list(iterable.elts), ast.Load())
    return iterable


def unwrap(node: ast.expr, symbols: Symbols) -> ast.expr:
    """`node` without the calls that change only its spelling."""
    while isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        qualified = symbols.qualified_name(node.func)
        if qualified not in SPELLINGS and qualified not in PATH_CLASSES:
            break
        node = node.args[0]
    return node


def parts(node: ast.expr, symbols: Symbols) -> list[ast.expr] | None:
    """The pieces a path is joined from, the base first; None when it is not joined here.

    A join call, a path class given several arguments, `+` and `/` over
    strings or paths, `%` and `str.format` on a literal template, and an
    f-string. A template that does not start with its first placeholder has
    its leading text as the base.
    """
    node = unwrap(node, symbols)
    if isinstance(node, ast.Call):
        qualified = symbols.qualified_name(node.func)
        if qualified in JOINS or (qualified in PATH_CLASSES and len(node.args) > 1):
            return list(node.args)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == 'format'
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)
        ):
            return _templated(node.func.value, node.func.value.value.startswith('{'), node.args)
        return None
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add | ast.Div):
            return [*_operands(node.left, node.op), node.right]
        if (
            isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            values = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
            return _templated(node.left, node.left.value.startswith('%'), values)
        return None
    if isinstance(node, ast.JoinedStr):
        return [
            value.value if isinstance(value, ast.FormattedValue) else value for value in node.values
        ]
    return None


def _operands(node: ast.expr, op: ast.operator) -> list[ast.expr]:
    """The operands of a chain of one operator, leftmost first."""
    if isinstance(node, ast.BinOp) and type(node.op) is type(op):
        return [*_operands(node.left, op), node.right]
    return [node]


def _templated(template: ast.expr, leads: bool, values: list[ast.expr]) -> list[ast.expr]:
    """A template's pieces: its first value is the base when the template starts with it."""
    return list(values) if leads and values else [template, *values]


def fixed(node: ast.expr, symbols: Symbols, seen: frozenset[str] = frozenset()) -> bool:
    """Whether the source fixes `node`: a literal, or a name that holds only literals.

    A module's own names, the names it imports and the builtins count as
    fixed; so does a local assigned only fixed values, or walking a literal
    sequence. A parameter, an attribute of one and any call's result do not.
    """
    node = unwrap(node, symbols)
    if node is PARAMETER:
        return False
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(fixed(element, symbols, seen) for element in node.elts)
    if isinstance(node, ast.JoinedStr):
        return all(
            fixed(value.value if isinstance(value, ast.FormattedValue) else value, symbols, seen)
            for value in node.values
        )
    if isinstance(node, ast.BinOp):
        return fixed(node.left, symbols, seen) and fixed(node.right, symbols, seen)
    if isinstance(node, ast.Attribute):
        return fixed(node.value, symbols, seen)
    if isinstance(node, ast.Subscript):
        return fixed(node.value, symbols, seen) and fixed(node.slice, symbols, seen)
    if isinstance(node, ast.Name):
        if node.id in seen:
            return True
        scope = symbols.binding_scope(node)
        if (
            scope is None
            or isinstance(scope, ast.Module | ast.ClassDef)
            or symbols.lookup(node).kind != LOCAL
        ):
            return True
        values = assigned(node, symbols)
        return values is not None and all(
            fixed(value, symbols, seen | {node.id}) for value in values
        )
    return False


def base(node: ast.expr, symbols: Symbols, seen: frozenset[str] = frozenset()) -> list[ast.expr]:
    """What `node` is under: its base, followed through joins and local names.

    One expression per way the function can arrive at it: a name assigned
    twice has the bases of both values. What cannot be followed further (a
    parameter, a call, an attribute) is itself a base.
    """
    node = unwrap(node, symbols)
    joined = parts(node, symbols)
    if joined is not None:
        return base(joined[0], symbols, seen)
    if isinstance(node, ast.Name) and node is not PARAMETER and node.id not in seen:
        values = assigned(node, symbols)
        if values is not None:
            return [found for value in values for found in base(value, symbols, seen | {node.id})]
    return [node]
