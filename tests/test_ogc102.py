"""OGC102, beyond its own examples."""

import pytest

from openglcontext_checks.engine import check_source


def _found(source, **options):
    options.setdefault('scopes', ['loader'])
    return check_source(source, codes=['OGC102'], **options)


def test_the_message_names_the_decode_the_value_and_the_check():
    (finding,) = _found('import base64\ndef f(payload):\n    return base64.b64decode(payload)\n')
    assert (finding.line, finding.column) == (3, 12)
    assert 'base64.b64decode(payload)' in finding.message
    assert 'OpenGLContext.loaders.resolver.check_size' in finding.message


def test_a_project_names_its_own_size_check():
    own = {'OGC102': ('game.limits.within',)}
    source = (
        'import zlib\nfrom game import limits\n'
        'def f(data):\n    limits.within(data)\n    return zlib.decompress(data)\n'
    )
    assert _found(source, sanctioned=own) == []
    assert len(_found(source)) == 1


def test_only_the_loader_scope_is_checked():
    assert _found('import zlib\ndef f(data):\n    return zlib.decompress(data)\n', scopes=[]) == []


def test_a_module_constant_is_the_program_s_own_data():
    source = 'import base64\n_PNG = "aGVsbG8="\ndef atlas():\n    return base64.b64decode(_PNG)\n'
    assert _found(source) == []


def test_a_comparison_after_the_decode_is_too_late():
    source = (
        'import base64\n'
        'def f(payload):\n'
        '    data = base64.b64decode(payload)\n'
        '    if len(payload) > 10:\n'
        '        raise ValueError\n'
    )
    assert len(_found(source)) == 1


def test_a_comparison_of_another_value_is_not_a_cap_on_this_one():
    source = (
        'import base64\n'
        'def f(payload, other):\n'
        '    if len(other) > 10:\n'
        '        raise ValueError\n'
        '    return base64.b64decode(payload)\n'
    )
    assert len(_found(source)) == 1


def test_a_check_in_another_function_does_not_count():
    source = (
        'import base64\n'
        'def g(payload):\n'
        '    assert len(payload) < 10\n'
        'def f(payload):\n'
        '    return base64.b64decode(payload)\n'
    )
    assert [finding.line for finding in _found(source)] == [5]


@pytest.mark.parametrize(
    'call',
    [
        'numpy.frombuffer(data, numpy.float32, count)',
        'numpy.frombuffer(data, numpy.float32, count=n * 3, offset=offset)',
        'numpy.frombuffer(data)',
        'numpy.empty(n)',
        'numpy.zeros((n, 3))',
    ],
)
def test_an_array_sized_by_a_computed_value_is_not_reported(call):
    source = 'import numpy\ndef f(data, count, n, offset):\n    return %s\n' % (call,)
    assert _found(source) == []


@pytest.mark.parametrize(
    'call',
    [
        'numpy.frombuffer(data, numpy.float32, accessor["count"])',
        'numpy.frombuffer(data, numpy.float32, offset=view.get("byteOffset", 0))',
        'numpy.empty(accessor["count"])',
        'numpy.full((accessor["count"], 3), 0.0)',
        'numpy.ones(shape=accessor["count"])',
    ],
)
def test_an_array_sized_by_a_document_field_is_reported(call):
    source = 'import numpy\ndef f(data, accessor, view):\n    return %s\n' % (call,)
    assert len(_found(source)) == 1


def test_a_decode_with_no_argument_has_nothing_to_size():
    assert _found('import base64\ndef f():\n    return base64.b64decode()\n') == []


def test_a_decode_at_module_level_of_a_literal_is_not_reported():
    assert _found('import zlib\nDATA = zlib.decompress(b"x")\n') == []
