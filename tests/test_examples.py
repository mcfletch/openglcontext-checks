"""Every rule's own VALID and INVALID examples, run as tests.

A rule module states what it flags by example: each VALID snippet produces no
finding of that rule's code, and each INVALID snippet produces findings on
exactly the lines it lists. A scoped rule's examples are checked as modules in
its scope.
"""

import re

import pytest

from openglcontext_checks.engine import check_source
from openglcontext_checks.rules import ALL_RULES


def _examples(kind):
    return [
        pytest.param(rule, example, id='%s-%s-%d' % (rule.code, kind, index))
        for rule in ALL_RULES
        for index, example in enumerate(getattr(rule, kind))
    ]


def _lines(rule, source):
    scopes = [rule.scope] if rule.scope else []
    return [finding.line for finding in check_source(source, codes=[rule.code], scopes=scopes)]


@pytest.mark.parametrize('rule, source', _examples('VALID'))
def test_a_valid_example_is_not_reported(rule, source):
    assert _lines(rule, source) == []


@pytest.mark.parametrize('rule, example', _examples('INVALID'))
def test_an_invalid_example_is_reported_on_the_lines_it_names(rule, example):
    assert _lines(rule, example.source) == list(example.lines)


@pytest.mark.parametrize('rule', ALL_RULES, ids=lambda rule: rule.code)
def test_a_rule_describes_itself_and_gives_examples_of_both_kinds(rule):
    assert re.fullmatch(r'OGC[0-9]{3}', rule.code)
    assert rule.name and rule.name == rule.name.strip()
    assert type(rule).__doc__ and len(type(rule).__doc__.split()) > 30
    assert rule.VALID and rule.INVALID


def test_every_code_is_distinct():
    codes = [rule.code for rule in ALL_RULES]
    assert len(codes) == len(set(codes))


@pytest.mark.parametrize(
    'rule', [rule for rule in ALL_RULES if rule.scope], ids=lambda rule: rule.code
)
def test_a_scoped_rule_is_silent_outside_its_scope(rule):
    for example in rule.INVALID:
        assert check_source(example.source, codes=[rule.code]) == []
