"""OGC101, beyond its own examples."""

import pytest

from openglcontext_checks.engine import check_source


def _found(source, **options):
    options.setdefault('scopes', ['loader'])
    return check_source(source, codes=['OGC101'], **options)


def test_the_message_names_the_conversion_the_field_and_the_reader():
    (finding,) = _found('def read(extras):\n    return float(extras["depth"])\n')
    assert (finding.line, finding.column) == (2, 12)
    assert "float() of extras['depth']" in finding.message
    assert 'OpenGLContext.loaders.documentvalues.DocumentValues' in finding.message


def test_a_project_names_its_own_reader():
    own = {'OGC101': ('game.levels.checked',)}
    (finding,) = _found('def read(d):\n    return int(d.get("n", 0))\n', sanctioned=own)
    assert finding.message.endswith('(game.levels.checked)')


def test_only_the_loader_scope_is_checked():
    assert _found('def read(d):\n    return int(d["n"])\n', scopes=[]) == []


@pytest.mark.parametrize(
    'expression',
    [
        'int(shape[0])',
        'float(values[index])',
        'int(counts.get(key, 0))',
        'int(d.get())',
        'float(x)',
        'int()',
        'round(d["n"])',
    ],
)
def test_an_index_a_variable_key_or_another_call_is_not_a_document_field(expression):
    source = 'def f(shape, values, index, counts, key, d, x):\n    return %s\n' % (expression,)
    assert _found(source) == []


def test_a_conversion_with_a_base_is_reported():
    assert len(_found('def f(d):\n    return int(d["mask"], base=16)\n')) == 1


def test_a_conversion_rebound_locally_is_not_the_builtin():
    source = 'def f(d):\n    float = str\n    return float(d["n"])\n'
    assert _found(source) == []


def test_bool_of_a_named_field_is_reported():
    """`bool('false')` is True: the octahedral hemisphere was read that way."""
    assert len(_found('def f(extras):\n    return bool(extras.get("hemi"))\n')) == 1


def test_a_field_of_the_module_s_own_table_is_not_a_document_value():
    source = (
        'HINTS = {"maxParticles": {"maximum": 10000}}\n'
        'def most():\n'
        '    return int(HINTS["maxParticles"]["maximum"]) + int(HINTS.get("step"))\n'
    )
    assert _found(source) == []


def test_a_field_of_a_parameter_s_table_is_a_document_value():
    source = 'HINTS = {}\ndef most(hints):\n    return int(hints["maxParticles"]["maximum"])\n'
    assert len(_found(source)) == 1


@pytest.mark.parametrize(
    'expression',
    [
        'float(extras.get("rate") or 1.0)',
        'int(d["n"] or 0)',
        'float(d.get("a") if flag else 2.0)',
        'float(2.0 if flag else d["a"])',
    ],
)
def test_a_default_given_with_or_or_a_condition_is_still_the_documents(expression):
    """`x.get(k) or default` reaches the conversion with the file's value."""
    source = 'def f(extras, d, flag):\n    return %s\n' % (expression,)
    assert len(_found(source)) == 1


def test_a_choice_between_the_programs_own_values_is_not_a_document_field():
    source = 'def f(a, b, flag):\n    return float(a or b) + float(1.0 if flag else 2.0)\n'
    assert _found(source) == []
