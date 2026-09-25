"""OGC161, beyond its own examples."""

from openglcontext_checks.engine import check_source


def _found(source):
    return check_source(source, codes=['OGC161'])


def test_a_read_is_named_and_the_alternative_given():
    (finding,) = _found('import os\nHOME = os.environ["HOME"]\n')
    assert (finding.line, finding.column) == (2, 8)
    assert finding.message.startswith('os.environ at import')
    assert 'in a function' in finding.message


def test_a_call_is_named_as_a_call():
    (finding,) = _found('import shutil\nshutil.rmtree("old")\n')
    assert finding.message.startswith('shutil.rmtree() at import')
    assert 'I/O' in finding.message


def test_a_chained_access_is_reported_once():
    assert len(_found('import os\nX = os.environ.get("X", os.environ.get("Y"))\n')) == 2


def test_an_aliased_import_is_resolved():
    source = 'import subprocess as sp\nfrom os import environ as env\nsp.run([])\nenv.copy()\n'
    assert [finding.line for finding in _found(source)] == [3, 4]


def test_a_function_named_like_one_in_the_set_is_not_it():
    assert _found('def getenv(name):\n    return name\nX = getenv("X")\n') == []


def test_a_class_inside_a_function_is_not_import_time():
    source = 'import os\ndef build():\n    class Local:\n        home = os.environ["HOME"]\n'
    assert _found(source) == []


def test_a_main_guard_written_either_way_round_is_recognised():
    source = 'import sys\nif "__main__" == __name__:\n    print(sys.argv)\n'
    assert _found(source) == []


def test_type_checking_through_the_typing_module_is_recognised():
    source = 'import os, typing\nif typing.TYPE_CHECKING:\n    X = os.environ\n'
    assert _found(source) == []


def test_an_ordinary_condition_is_still_import_time():
    source = 'import os, sys\nif sys.platform == "win32":\n    X = os.environ\n'
    assert [finding.line for finding in _found(source)] == [3]


def test_the_test_of_a_main_guard_is_import_time():
    """Only the guarded body is skipped."""
    source = 'import os\nif os.environ.get("RUN") and __name__ == "__main__":\n    pass\n'
    assert [finding.line for finding in _found(source)] == [2]


def test_a_reference_to_a_function_that_is_not_called_is_not_reported():
    assert _found('import os\nLOOKUP = os.getenv\n') == []
