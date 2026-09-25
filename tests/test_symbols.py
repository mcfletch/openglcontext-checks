"""What a name in a module is bound to."""

import ast
import textwrap

from openglcontext_checks.symbols import BUILTIN, IMPORTED, LOCAL, UNBOUND, Symbols


def _names(source):
    tree = ast.parse(textwrap.dedent(source))
    symbols = Symbols(tree)
    return tree, symbols


def _call_target(tree, name):
    """The function expression of the first call whose text is `name`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == name:
            return node.func
    raise AssertionError('no call to %s' % (name,))


def test_each_import_form_resolves_to_the_qualified_name():
    tree, symbols = _names("""
        import OpenGL.GL as GL
        import OpenGL.GLU
        from OpenGL import GLES3
        from OpenGL.raw.GL import glFinish as finish
        GL.glFlush()
        OpenGL.GLU.gluNewQuadric()
        GLES3.glClear()
        finish()
    """)
    assert symbols.qualified_name(_call_target(tree, 'GL.glFlush')) == 'OpenGL.GL.glFlush'
    assert symbols.qualified_name(_call_target(tree, 'OpenGL.GLU.gluNewQuadric')) == (
        'OpenGL.GLU.gluNewQuadric'
    )
    assert symbols.qualified_name(_call_target(tree, 'GLES3.glClear')) == 'OpenGL.GLES3.glClear'
    assert symbols.qualified_name(_call_target(tree, 'finish')) == 'OpenGL.raw.GL.glFinish'


def test_a_relative_import_keeps_its_dots():
    tree, symbols = _names("""
        from . import sibling
        from ..pkg import thing
        sibling.run()
        thing()
    """)
    assert symbols.qualified_name(_call_target(tree, 'sibling.run')) == '.sibling.run'
    assert symbols.qualified_name(_call_target(tree, 'thing')) == '..pkg.thing'


def test_a_builtin_is_builtin_until_something_rebinds_it():
    tree, symbols = _names("""
        open('a')
        def reader(open):
            open('b')
    """)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert symbols.lookup(calls[0].func).kind == BUILTIN
    assert symbols.qualified_name(calls[0].func) == 'builtins.open'
    assert symbols.lookup(calls[1].func).kind == LOCAL
    assert symbols.qualified_name(calls[1].func) is None


def test_an_import_in_a_function_is_seen_only_inside_it():
    tree, symbols = _names("""
        def release():
            from OpenGL.GL import glDeleteTextures
            glDeleteTextures([1])
        def elsewhere():
            glDeleteTextures([2])
    """)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    resolved = sorted(
        (call.args[0].elts[0].value, symbols.lookup(call.func).kind) for call in calls
    )
    assert resolved == [(1, IMPORTED), (2, UNBOUND)]


def test_an_import_outranks_the_fallback_assigned_beside_it():
    tree, symbols = _names("""
        try:
            from OpenGL.GL import glFinish
        except ImportError:
            glFinish = None
        glFinish()
    """)
    assert symbols.qualified_name(_call_target(tree, 'glFinish')) == 'OpenGL.GL.glFinish'


def test_a_class_body_is_not_visible_from_its_methods():
    tree, symbols = _names("""
        class Holder:
            from OpenGL import GL
            GL.glFinish()
            def method(self):
                GL.glFlush()
    """)
    assert symbols.qualified_name(_call_target(tree, 'GL.glFinish')) == 'OpenGL.GL.glFinish'
    assert symbols.lookup(_call_target(tree, 'GL.glFlush').value).kind == UNBOUND


def test_defaults_and_decorators_belong_to_the_enclosing_scope():
    tree, symbols = _names("""
        import os
        def configured(path=os.getcwd(), os=None):
            return os
    """)
    assert symbols.qualified_name(_call_target(tree, 'os.getcwd')) == 'os.getcwd'
    function = tree.body[1]
    assert symbols.scope_of(function.args.defaults[0]) is tree
    assert symbols.scope_of(function.body[0]) is function


def test_every_way_of_binding_a_name_is_local():
    tree, symbols = _names("""
        import contextlib
        for a in (): pass
        with contextlib.nullcontext() as b: pass
        try: pass
        except Exception as c: pass
        match 1:
            case [d, *e]: pass
            case {'k': 1, **f}: pass
            case {'only': 2}: pass
        g = lambda h: h
        class I: pass
        async def j(k, *l, m, **n): pass
        del a
        a(), b(), c(), d(), e(), f(), g(), h(), I(), j(), k(), l(), m(), n()
    """)
    calls = {
        ast.unparse(node.func): node.func
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    kinds = {name: symbols.lookup(node).kind for name, node in calls.items()}
    assert kinds == {
        'a': LOCAL,
        'b': LOCAL,
        'c': LOCAL,
        'd': LOCAL,
        'e': LOCAL,
        'f': LOCAL,
        'g': LOCAL,
        'h': UNBOUND,
        'I': LOCAL,
        'j': LOCAL,
        'k': UNBOUND,
        'l': UNBOUND,
        'm': UNBOUND,
        'n': UNBOUND,
    }


def test_a_star_import_is_reported_for_the_scope_that_sees_it():
    tree, symbols = _names("""
        from OpenGL.GL import *
        def draw():
            from OpenGL.GLU import *
            glFinish()
        glFlush()
    """)
    assert symbols.star_modules(_call_target(tree, 'glFinish')) == ('OpenGL.GLU', 'OpenGL.GL')
    assert symbols.star_modules(_call_target(tree, 'glFlush')) == ('OpenGL.GL',)


def test_an_expression_that_is_not_a_name_has_no_qualified_name():
    tree, symbols = _names("""
        factory()()
        items[0].method()
    """)
    assert symbols.qualified_name(_call_target(tree, 'factory()')) is None
    assert symbols.qualified_name(_call_target(tree, 'items[0].method')) is None


def test_parents_and_ancestors_lead_back_to_the_module():
    tree, symbols = _names("""
        def outer():
            return value
    """)
    name = tree.body[0].body[0].value
    assert symbols.parent(name) is tree.body[0].body[0]
    assert list(symbols.ancestors(name)) == [tree.body[0].body[0], tree.body[0], tree]
    assert symbols.parent(tree) is None


def test_a_deeply_nested_expression_does_not_exhaust_the_stack():
    source = 'value = ' + ' + '.join(['x'] * 5000) + '\n'
    tree = ast.parse(source)
    symbols = Symbols(tree)
    assert symbols.scope_of(tree.body[0].value) is tree


def test_a_star_import_in_a_class_body_is_not_seen_from_its_methods():
    tree, symbols = _names("""
        class Holder:
            from OpenGL.GL import *
            def method(self):
                glFinish()
    """)
    assert symbols.star_modules(_call_target(tree, 'glFinish')) == ()


def test_module_and_class_bodies_run_at_import_and_function_bodies_do_not():
    tree, symbols = _names("""
        import os
        X = os.sep
        class Holder:
            Y = os.sep
            def method(self, z=os.sep):
                return os.sep
            f = lambda: os.sep
        def factory():
            class Local:
                W = os.sep
    """)
    seps = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    at_import = sorted(node.lineno for node in seps if symbols.runs_at_import(node))
    assert at_import == [3, 5, 6]


def test_the_enclosing_function_is_the_innermost_one():
    tree, symbols = _names("""
        def outer():
            inner = lambda: value
            return other
        top = level
    """)
    outer = tree.body[0]
    lambda_body = outer.body[0].value.body
    assert symbols.enclosing_function(lambda_body) is outer.body[0].value
    assert symbols.enclosing_function(outer.body[1].value) is outer
    assert symbols.enclosing_function(tree.body[1].value) is None
