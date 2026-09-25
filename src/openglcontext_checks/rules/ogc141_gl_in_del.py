"""OGC141: a GL call in `__del__`."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet
from .gl import gl_function

if TYPE_CHECKING:
    from ..engine import Module


class GlInDel(Rule):
    """A call to an OpenGL function inside a `__del__` method.

    A finaliser runs when the collector reaches the object: on whichever
    thread that is, at whatever point in a frame, with whatever context is
    current there, or with none at all during interpreter shutdown. A
    `glDelete*` made there deletes a name in the wrong context, or raises
    because there is no context, or crashes in the driver.

    The functions counted are those of `OpenGL.GL`, the `OpenGL.GLES*`
    modules and their `OpenGL.raw` counterparts, reached through any import
    form (`import OpenGL.GL as GL`, `from OpenGL import GL`,
    `from OpenGL.GL import glDeleteTextures`). After a star import from one of
    those modules, a name spelled `gl` and a capital letter that nothing in
    the module binds counts too, as does a parameter whose default is one of
    those functions and which the body never rebinds (`def __del__(self,
    glDeleteLists=glDeleteLists)`). A lambda or function defined inside
    `__del__` is not the finaliser's own call and is not reported.

    Use instead: queue the release for the context that owns the name, and
    delete it there, where that context is current. In OpenGLContext that is
    the pass disposal chain (`passes/disposal.PassResources`) or a node's
    `dispose()`.
    """

    code = 'OGC141'
    name = 'GL call in __del__'
    nodes = (ast.Call,)

    VALID = (
        snippet("""
            from OpenGL import GL

            class Texture:
                def __del__(self):
                    PENDING.append(self.name)

                def release(self):
                    GL.glDeleteTextures([self.name])
        """),
        snippet("""
            from OpenGL.GL import glDeleteBuffers

            class Buffer:
                def __del__(self):
                    self.owner.later(lambda: glDeleteBuffers(1, [self.name]))
        """),
        snippet("""
            from OpenGL.GLU import gluDeleteQuadric

            class Quadric:
                def __del__(self):
                    gluDeleteQuadric(self.quadric)
        """),
        snippet("""
            from OpenGL.GL import *

            def glRelease(name):
                PENDING.append(name)

            class Texture:
                def __del__(self):
                    glRelease(self.name)
        """),
        snippet("""
            class Globber:
                def __del__(self):
                    glDeleteEverything()
        """),
        snippet("""
            from OpenGL.GL import glDeleteLists

            def forget(name):
                PENDING.append(name)

            class Lists:
                def __del__(self, release=forget):
                    release(self.list)
        """),
        snippet("""
            from OpenGL.GL import glDeleteLists

            class Lists:
                def __del__(self, glDeleteLists=glDeleteLists):
                    glDeleteLists = PENDING.append
                    glDeleteLists(self.list)
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                from OpenGL import GL

                class Texture:
                    def __del__(self):
                        GL.glDeleteTextures([self.name])
            """),
            (5,),
        ),
        Invalid(
            snippet("""
                class Buffer:
                    def __del__(self):
                        from OpenGL.GL import glDeleteBuffers
                        glDeleteBuffers(1, [self.name])
            """),
            (4,),
        ),
        Invalid(
            snippet("""
                from OpenGL.GL import *

                class Mesh:
                    def __del__(self):
                        if self.vao:
                            glDeleteVertexArrays(1, [self.vao])
            """),
            (6,),
        ),
        Invalid(
            snippet("""
                import OpenGL.GL
                import OpenGL.raw.GL.VERSION.GL_1_1 as raw
                from OpenGL import GLES3

                class Target:
                    def __del__(self):
                        OpenGL.GL.glFinish()
                        raw.glDeleteTextures(1, self.names)
                        GLES3.glDeleteFramebuffers(1, [self.fbo])
            """),
            (7, 8, 9),
        ),
        Invalid(
            snippet("""
                from OpenGL.GL import glDeleteLists

                class Lists:
                    def __del__(self, glDeleteLists=glDeleteLists):
                        glDeleteLists(self.list, 1)
            """),
            (5,),
        ),
        Invalid(
            snippet("""
                from OpenGL.GL import *

                class Lists:
                    def __del__(self, delete=glDeleteLists, *, keep=None, name, finish=glFinish):
                        delete(self.list, 1)
                        finish()
            """),
            (5, 6),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Call)
        symbols = module.symbols
        function = symbols.enclosing_function(node)
        if not isinstance(function, ast.FunctionDef) or function.name != '__del__':
            return
        if gl_function(node, symbols) is None:
            return
        yield self.finding(
            node,
            '%s called in __del__: a finaliser runs on whichever thread collects the object, '
            'with whatever context is current there or none; queue the release for the owning '
            'context (a disposal chain) instead' % (ast.unparse(node.func),),
        )
