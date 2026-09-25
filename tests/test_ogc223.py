"""OGC223, beyond its own examples."""

from openglcontext_checks.engine import check_source


def _found(source):
    return check_source(source, codes=['OGC223'], scopes=['test'])


def test_the_message_names_the_alternatives():
    source = 'def test_x():\n    try:\n        run()\n    except OSError:\n        pass\n'
    (finding,) = _found(source)
    assert (finding.line, finding.column) == (4, 5)
    assert finding.message.startswith('except with only pass in test_x')
    assert 'pytest.raises' in finding.message


def test_a_handler_in_a_helper_nested_in_a_test_is_inside_the_test():
    source = (
        'def test_x():\n    def attempt():\n        try:\n            run()\n'
        '        except OSError:\n            pass\n    attempt()\n    assert True\n'
    )
    assert [finding.line for finding in _found(source)] == [5]


def test_a_handler_that_does_something_is_not_reported():
    source = (
        'def test_x():\n    try:\n        run()\n    except OSError:\n        pass\n        log()\n'
    )
    assert _found(source) == []


def test_a_handler_at_module_level_of_a_test_module_is_not_in_a_test():
    source = 'try:\n    import x\nexcept ImportError:\n    pass\n'
    assert _found(source) == []
