"""Parsing a module, running rules over it and applying suppressions."""

import ast

import pytest

from openglcontext_checks.engine import ParseError, check_source, parse_module, run_rules
from openglcontext_checks.findings import Finding
from openglcontext_checks.rules.base import Rule


class NamesCalledEval(Rule):
    """A rule for these tests: every call to a function named `eval`."""

    code = 'OGC901'
    name = 'eval called'
    nodes = (ast.Call,)

    def visit(self, node, module):
        if isinstance(node.func, ast.Name) and node.func.id == 'eval':
            yield self.finding(node, 'eval called')


class FirstLineInScope(Rule):
    """A module-level rule that only runs in the `demo` scope."""

    code = 'OGC902'
    name = 'demo module'
    scope = 'demo'

    def check_module(self, module):
        yield self.finding(1, 'a demo module')


class Silent(Rule):
    """The base class's own behaviour: nothing to report."""

    code = 'OGC903'
    name = 'silent'
    nodes = (ast.Name,)


class FirstLineOutsideScripts(Rule):
    """A module-level rule that runs everywhere but the `script` scope."""

    code = 'OGC904'
    name = 'not a script'
    exempt_scope = 'script'

    def check_module(self, module):
        yield self.finding(1, 'not a script')


RULES = [NamesCalledEval(), FirstLineInScope(), Silent()]


def _run(source, scopes=()):
    module = parse_module(source.encode('utf-8'), 'example.py', frozenset(scopes))
    return run_rules(module, RULES)


def test_a_rule_reports_the_node_it_was_handed():
    assert _run('x = 1\nvalue = eval(text)\n') == [Finding(2, 9, 'OGC901', 'eval called')]


def test_a_scoped_rule_runs_only_in_its_scope():
    assert [finding.code for finding in _run('x = 1\n', scopes=['demo'])] == ['OGC902']
    assert _run('x = 1\n') == []


def test_a_rule_does_not_run_in_the_scope_it_is_exempt_from():
    rules = [FirstLineOutsideScripts()]
    module = parse_module(b'x = 1\n', 'example.py', frozenset({'test'}))
    assert [finding.code for finding in run_rules(module, rules)] == ['OGC904']
    module = parse_module(b'x = 1\n', 'example.py', frozenset({'test', 'script'}))
    assert run_rules(module, rules) == []


def test_findings_come_back_in_source_order():
    found = _run('eval(a)\neval(b); eval(c)\n', scopes=['demo'])
    assert [(finding.line, finding.column, finding.code) for finding in found] == [
        (1, 1, 'OGC901'),
        (1, 1, 'OGC902'),
        (2, 1, 'OGC901'),
        (2, 10, 'OGC901'),
    ]


def test_a_reasoned_noqa_suppresses_the_code_it_names():
    assert _run('eval(a)  # noqa: OGC901 the input is a literal\n') == []


def test_a_noqa_shared_with_ruff_suppresses_too():
    assert _run('eval(a)  # noqa: S307, OGC901 the input is a literal\n') == []


@pytest.mark.parametrize(
    'comment',
    [
        '# noqa: OGC901',
        '# noqa',
        '# noqa: OGC999 another code',
        '# type: ignore[OGC901] wrong tool',
    ],
)
def test_a_noqa_that_does_not_name_the_code_with_a_reason_suppresses_nothing(comment):
    assert [finding.code for finding in _run('eval(a)  %s\n' % (comment,))] == ['OGC901']


def test_a_suppression_applies_to_its_own_line_only():
    found = _run('eval(a)  # noqa: OGC901 literal\neval(b)\n')
    assert [finding.line for finding in found] == [2]


def test_source_that_does_not_parse_is_an_error_with_a_position():
    with pytest.raises(ParseError) as caught:
        parse_module(b'def broken(:\n', 'broken.py')
    assert caught.value.line == 1
    assert caught.value.column >= 1
    assert 'broken.py:1:' in str(caught.value)


def test_a_null_byte_is_an_error_on_every_supported_python():
    """A ValueError from `ast` up to 3.11, a SyntaxError from 3.12 on."""
    with pytest.raises(ParseError) as caught:
        parse_module(b'x = 1\n\x00\n', 'nul.py')
    assert str(caught.value).startswith('nul.py:')


def test_an_error_without_a_position_is_placed_at_the_start():
    """The tokenizer's own errors carry no line or offset attributes."""
    import unittest.mock

    import openglcontext_checks.engine as engine

    def refuse(_source):
        raise engine.tokenize.TokenError('EOF in multi-line statement')

    with (
        unittest.mock.patch.object(engine, 'read_pragmas', refuse),
        pytest.raises(ParseError) as caught,
    ):
        parse_module(b'x = 1\n', 'odd.py')
    assert (caught.value.line, caught.value.column) == (1, 1)
    assert 'EOF in multi-line statement' in caught.value.message


def test_a_syntax_warning_in_the_checked_source_is_not_raised():
    """An invalid escape is a warning from the compiler, and the module still parses."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter('error')
        module = parse_module(b"pattern = '\\d+'\n", 'escape.py')
    assert module.path == 'escape.py'


def test_check_source_runs_the_registered_rules_it_is_asked_for():
    """With nothing registered for a code, nothing is reported."""
    assert check_source('x = 1\n', codes=[]) == []


def test_a_finding_formats_as_path_line_column_code_message():
    assert Finding(3, 7, 'OGC131', 'id() as a key').format('pkg/mod.py') == (
        'pkg/mod.py:3:7: OGC131 id() as a key'
    )


def test_a_rule_reports_a_line_or_a_node():
    rule = NamesCalledEval()
    node = ast.parse('eval(x)\n').body[0].value
    assert rule.finding(node, 'm') == Finding(1, 1, 'OGC901', 'm')
    assert rule.finding(4, 'm') == Finding(4, 1, 'OGC901', 'm')
