"""OGC151, beyond its own examples."""

import pytest

from openglcontext_checks.engine import check_source

HEADER = 'from OpenGL.GL import *\nfrom OpenGL import GL\n'


def _found(body, **options):
    options.setdefault('scopes', ['pass'])
    lines = ''.join('    %s\n' % (line,) for line in body.splitlines())
    return check_source(HEADER + 'def draw(self, fbo):\n' + lines, codes=['OGC151'], **options)


def test_the_message_names_the_call_and_the_finally():
    (finding,) = _found('glEnable(GL_SCISSOR_TEST)\nself.render()')
    assert (finding.line, finding.column) == (4, 5)
    assert 'glEnable(GL_SCISSOR_TEST)' in finding.message
    assert 'finally' in finding.message


def test_a_project_names_its_state_managers():
    own = {'OGC151': ('engine.glstate.saved',)}
    body = 'from engine import glstate\nwith glstate.saved():\n    glEnable(GL_BLEND)\n    self.render()'
    assert _found(body, sanctioned=own) == []
    assert len(_found(body)) == 1
    (finding,) = _found('glUseProgram(0)', sanctioned=own)
    assert finding.message.endswith('(engine.glstate.saved)')


def test_only_the_pass_scope_is_checked():
    assert _found('glEnable(GL_BLEND)', scopes=[]) == []


@pytest.mark.parametrize(
    'body',
    [
        'glEnable(GL_BLEND)\ntry:\n    self.render()\nfinally:\n    glDisable(GL_BLEND)',
        'try:\n    glEnable(GL_BLEND)\n    self.render()\nfinally:\n    glDisable(GL_BLEND)',
        'GL.glBindFramebuffer(GL_FRAMEBUFFER, fbo)\ntry:\n    self.render()\n'
        'finally:\n    GL.glBindFramebuffer(GL_FRAMEBUFFER, 0)',
        'glScissor(0, 0, 4, 4)\ntry:\n    self.render()\nfinally:\n    glDisable(GL.GL_SCISSOR_TEST)',
        'GL.glEnable(GL.GL_BLEND)\ntry:\n    self.render()\nfinally:\n    glDisable(GL_BLEND)',
        'if fbo:\n    glScissor(0, 0, 4, 4)\ntry:\n    self.render()\nfinally:\n    glScissor(0, 0, 8, 8)',
        'glCullFace(GL_FRONT)\ntry:\n    self.render()\nexcept ValueError:\n    pass\n'
        'finally:\n    glCullFace(GL_BACK)',
        'try:\n    self.render()\nexcept ValueError:\n    glDisable(GL_BLEND)\n'
        'finally:\n    glEnable(GL_BLEND)',
        'glDisable(GL_DEPTH_TEST)\ntry:\n    self.render()\nfinally:\n    glEnable(GL_DEPTH_TEST)',
    ],
)
def test_a_change_restored_in_a_finally_is_not_reported(body):
    assert _found(body) == []


@pytest.mark.parametrize(
    'body, lines',
    [
        ('glEnable(GL_BLEND)\nself.render()\nglDisable(GL_BLEND)', [4, 6]),
        (
            'glEnable(GL_BLEND)\ntry:\n    self.render()\nfinally:\n    glDisable(GL_DEPTH_TEST)',
            [4],
        ),
        ('try:\n    self.render()\nfinally:\n    glDisable(GL_BLEND)\nglEnable(GL_BLEND)', [8]),
        (
            'glUseProgram(1)\ntry:\n    self.render()\nfinally:\n    glBindFramebuffer(GL_FRAMEBUFFER, 0)',
            [4],
        ),
        ('with self.lock:\n    glEnable(GL_BLEND)\n    self.render()', [5]),
        (
            'def later():\n    glEnable(GL_BLEND)\ntry:\n    later()\nfinally:\n    glDisable(GL_BLEND)',
            [5],
        ),
        ('try:\n    self.render()\nfinally:\n    pass\nglCullFace(GL_FRONT)', [8]),
        ('try:\n    glEnable(GL_BLEND)\nfinally:\n    self.render()', [5]),
        (
            'glUseProgram(self.program)\nif fbo:\n    try:\n        self.render()\n'
            '    finally:\n        glUseProgram(0)',
            [4],
        ),
        (
            'glEnable(capabilities[0])\ntry:\n    pass\nfinally:\n    glDisable(capabilities[1])',
            [4],
        ),
        ('glScissor(0, 0, 4, 4)\ntry:\n    pass\nfinally:\n    glDisable(GL_BLEND)', [4]),
    ],
)
def test_a_change_nothing_restores_on_every_exit_is_reported(body, lines):
    assert [finding.line for finding in _found(body)] == lines


def test_other_gl_calls_and_other_modules_are_not_state_changes():
    body = 'glClear(GL_COLOR_BUFFER_BIT)\nGL.glDrawArrays(GL_TRIANGLES, 0, 3)\nself.glEnable(1)'
    assert _found(body) == []


def test_a_change_at_module_level_is_restored_by_a_module_level_finally():
    source = (
        'from OpenGL.GL import glEnable, glDisable\n'
        'glEnable(1)\ntry:\n    pass\nfinally:\n    glDisable(1)\n'
    )
    assert check_source(source, codes=['OGC151'], scopes=['pass']) == []
