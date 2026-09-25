"""OGC222, beyond its own examples."""

import pytest

from openglcontext_checks.engine import check_source


def _found(source):
    return check_source(source, codes=['OGC222'], scopes=['test'])


def test_the_message_names_the_test_and_the_alternatives():
    (finding,) = _found('@decorated\ndef test_draws():\n    draw()\n')
    assert (finding.line, finding.column) == (2, 1)
    assert finding.message.startswith('test_draws has no assertion')
    assert 'pytest.raises' in finding.message


@pytest.mark.parametrize(
    'body',
    [
        'pytest.warns(UserWarning, run)',
        'pytest.fail("never")',
        'pytest.deprecated_call(run)',
        'self.fail("never")',
        '_assert_close(a, b)',
        'expect(value).to_be(1)',
        'verify_frame(frame)',
        'numpy.testing.assert_allclose(a, b)',
    ],
)
def test_each_kind_of_assertion_counts(body):
    source = 'import pytest\nclass TestX:\n    def test_it(self):\n        %s\n' % (body,)
    assert _found(source) == []


def test_a_bare_raise_is_not_an_assertion():
    source = 'def test_rethrows():\n    try:\n        run()\n    except Exception:\n        raise\n'
    assert len(_found(source)) == 1


def test_a_test_in_a_nested_class_or_function_is_not_collected_here():
    source = (
        'class Outer:\n    class TestInner:\n        def test_x(self):\n            run()\n'
        'def factory():\n    def test_y():\n        run()\n'
    )
    assert _found(source) == []


def test_a_function_not_named_as_a_test_is_not_one():
    assert _found('def check_all():\n    run()\n') == []


def test_a_call_through_an_expression_is_not_named():
    assert len(_found('def test_x():\n    handlers[0]()\n')) == 1


def _helpers(helpers, call, *, cls=''):
    """A module defining `helpers`, and a test that makes `call`."""
    test = 'def test_it(self):\n    %s\n' % (call,)
    if cls:
        test = '%s\n' % (cls,) + ''.join('    ' + line + '\n' for line in test.splitlines())
    return 'import pytest\n%s\n%s' % (helpers, test)


@pytest.mark.parametrize(
    'helpers, call, cls',
    [
        ('def _close(a):\n    assert a\n', '_close(1)', ''),
        ('def _close(a):\n    _close(a)\n    assert a\n', '_close(1)', ''),
        (
            'class Base:\n    def _close(self):\n        assert True\n',
            'self._close()',
            'class TestX(Base):',
        ),
        (
            'class Base:\n    def _close(self):\n        assert True\n'
            'class Middle(object, mod.Mixin, Base):\n    pass\n',
            'self._close()',
            'class TestX(Middle):',
        ),
    ],
)
def test_a_helper_in_the_module_that_asserts_counts(helpers, call, cls):
    assert _found(_helpers(helpers, call, cls=cls)) == []


@pytest.mark.parametrize(
    'helpers, call, cls',
    [
        # Imported, not the module's own function.
        ('from helpers import _close\n', '_close(1)', ''),
        # Rebound after its definition: the call reads the later binding.
        ('def _close(a):\n    assert a\n_close = make()\n', '_close(1)', ''),
        # Defined conditionally: which one runs is not in the syntax.
        ('if FAST:\n    def _close(a):\n        assert a\n', '_close(1)', ''),
        # A class is constructed, not run as a helper.
        ('class _Close:\n    def __init__(self):\n        assert True\n', '_Close()', ''),
        # A method on something other than the test's own self.
        (
            'class Base:\n    def _close(self):\n        assert True\n',
            'other._close()',
            'class TestX(Base):',
        ),
        ('', 'self.a.b()', 'class TestX:'),
        # Found on the class as an attribute, so the base's method is not it.
        (
            'class Base:\n    def _close(self):\n        assert True\n',
            'self._close()',
            'class TestX(Base):\n    _close = staticmethod(print)',
        ),
        # A base that is imported, or bound to something other than a class.
        ('from lib import Base\nMixin = make()\n', 'self._close()', 'class TestX(Base, Mixin):'),
        # A base named twice is looked through once.
        ('class Base:\n    pass\n', 'self._close()', 'class TestX(Base, Base):'),
    ],
)
def test_a_call_the_syntax_cannot_follow_to_an_assertion_does_not_count(helpers, call, cls):
    assert len(_found(_helpers(helpers, call, cls=cls))) == 1


def test_self_in_a_module_level_helper_is_not_a_method_s_self():
    source = (
        'def _run(self):\n    self._close()\n'
        'def _bare():\n    x._close()\n'
        'class TestX:\n    def _close(self):\n        assert True\n'
        '    def test_it(self):\n        _run(self)\n        _bare()\n'
    )
    assert len(_found(source)) == 1
