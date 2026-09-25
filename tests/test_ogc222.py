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
