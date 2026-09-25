"""Which calls are calls to OpenGL."""

from __future__ import annotations

import ast

from ..symbols import UNBOUND, Symbols


def gl_function(node: ast.Call, symbols: Symbols) -> str | None:
    """The OpenGL function `node` calls (`glEnable`), or None when it calls another.

    The functions counted are those of `OpenGL.GL`, the `OpenGL.GLES*`
    modules and their `OpenGL.raw` counterparts, reached through any import
    form. After a star import from one of those modules, a name spelled `gl`
    and a capital letter or digit that nothing in the module binds counts too.
    A parameter whose default is such a function, and which the function body
    never rebinds, counts as that function: `def __del__(self,
    glDeleteLists=glDeleteLists)` calls OpenGL whenever it is called with the
    default, which is how the collector calls it.
    """
    function = _gl_reference(node.func, symbols)
    if function is None and isinstance(node.func, ast.Name):
        default = _parameter_default(node.func, symbols)
        if default is not None:
            function = _gl_reference(default, symbols)
    return function


def _gl_reference(expression: ast.expr, symbols: Symbols) -> str | None:
    """The OpenGL function `expression` names, or None when it names another."""
    qualified = symbols.qualified_name(expression)
    if qualified is not None:
        module, _, function = qualified.rpartition('.')
        return function if is_gl_module(module) else None
    if (
        isinstance(expression, ast.Name)
        and _looks_like_gl(expression.id)
        and symbols.lookup(expression).kind == UNBOUND
        and any(is_gl_module(star) for star in symbols.star_modules(expression))
    ):
        return expression.id
    return None


def _parameter_default(name: ast.Name, symbols: Symbols) -> ast.expr | None:
    """The default of the parameter `name` reads, if the function never rebinds it."""
    function = symbols.binding_scope(name)
    if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return None
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: dict[str, ast.expr] = dict(
        zip(
            (argument.arg for argument in positional[len(positional) - len(arguments.defaults):]),
            arguments.defaults,
            strict=True,
        )
    )
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if default is not None:
            defaults[argument.arg] = default
    default = defaults.get(name.id)
    if default is None:
        return None
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Name)
            and node.id == name.id
            and not isinstance(node.ctx, ast.Load)
            and symbols.scope_of(node) is function
        ):
            return None
    return default


def is_gl_module(name: str) -> bool:
    """Whether `name` is OpenGL.GL, an OpenGL.GLES* module, a raw one, or inside one."""
    parts = name.split('.')
    if parts[0] != 'OpenGL' or len(parts) < 2:
        return False
    if parts[1] == 'raw':
        parts = parts[1:]
        if len(parts) < 2:
            return False
    return parts[1] == 'GL' or parts[1].startswith('GLES')


def _looks_like_gl(name: str) -> bool:
    """Whether `name` is spelled as a GL entry point: `gl` and a capital or digit."""
    return len(name) > 2 and name.startswith('gl') and (name[2].isupper() or name[2].isdigit())
