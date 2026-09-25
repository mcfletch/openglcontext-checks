"""OGC221, beyond its own examples."""

from openglcontext_checks.engine import check_source


def _found(source):
    return check_source(source, codes=['OGC221'], scopes=['test'])


def test_the_message_names_the_call_and_the_alternatives():
    source = 'import pytest\ntry:\n    import x\nexcept ImportError:\n    pytest.skip("no x")\n'
    (finding,) = _found(source)
    assert (finding.line, finding.column) == (5, 5)
    assert finding.message.startswith('pytest.skip() in an except handler')
    assert 'importorskip' in finding.message


def test_a_skip_in_a_function_defined_in_the_handler_is_not_the_handler_s():
    source = (
        'import pytest\ntry:\n    import x\nexcept ImportError:\n'
        '    def later():\n        pytest.skip("no x")\n'
    )
    assert _found(source) == []


def test_a_skip_in_the_else_or_finally_is_not_in_the_handler():
    source = (
        'import pytest\ntry:\n    import x\nexcept ImportError:\n    x = None\n'
        'else:\n    pytest.skip("has x")\nfinally:\n    pytest.xfail("always")\n'
    )
    assert _found(source) == []


def test_another_module_s_skip_is_not_pytest_s():
    source = 'import unittest\ntry:\n    import x\nexcept ImportError:\n    unittest.skip("x")\n'
    assert _found(source) == []
