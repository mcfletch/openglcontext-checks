"""OGC141, beyond its own examples."""

from openglcontext_checks.engine import check_source


def _found(source):
    return check_source(source, codes=['OGC141'])


def test_the_message_names_the_function_and_the_alternative():
    source = 'from OpenGL import GL\nclass T:\n    def __del__(self):\n        GL.glFinish()\n'
    (finding,) = _found(source)
    assert (finding.line, finding.column) == (4, 9)
    assert 'GL.glFinish' in finding.message
    assert 'disposal' in finding.message


def test_a_gl_call_outside_a_finaliser_is_not_reported():
    assert _found('from OpenGL import GL\ndef release():\n    GL.glFinish()\n') == []


def test_a_star_import_from_another_module_does_not_make_gl_names_gl():
    source = 'from mylib import *\nclass T:\n    def __del__(self):\n        glRelease()\n'
    assert _found(source) == []


def test_a_star_imported_name_must_look_like_a_gl_function():
    source = 'from OpenGL.GL import *\nclass T:\n    def __del__(self):\n        globals()\n'
    assert _found(source) == []


def test_a_module_level_del_function_is_a_finaliser_too():
    """Assigned to a class later, a plain function runs as one."""
    source = 'from OpenGL import GL\ndef __del__(self):\n    GL.glFinish()\n'
    assert len(_found(source)) == 1


def test_a_call_through_an_expression_has_nothing_to_resolve():
    source = 'class T:\n    def __del__(self):\n        self.handlers[0]()\n'
    assert _found(source) == []


def test_the_module_itself_is_not_a_gl_function():
    source = 'import OpenGL\nclass T:\n    def __del__(self):\n        OpenGL.GL()\n'
    assert _found(source) == []


def test_the_raw_package_itself_and_raw_glu_are_not_gl():
    source = (
        'import OpenGL.raw\nfrom OpenGL.raw import GLU\n'
        'class T:\n    def __del__(self):\n        OpenGL.raw.anything()\n'
        '        GLU.gluDeleteQuadric(self.q)\n'
    )
    assert _found(source) == []
