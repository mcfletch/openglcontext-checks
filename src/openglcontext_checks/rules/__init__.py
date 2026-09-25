"""The rules, by code."""

from __future__ import annotations

from .base import Invalid, Rule, snippet
from .ogc131_id_key import IdAsKey
from .ogc141_gl_in_del import GlInDel
from .ogc161_import_time import WorkAtImport
from .ogc201_unreasoned_suppression import UnreasonedSuppression
from .ogc221_skip_in_except import SkipInExcept
from .ogc222_test_without_assertion import TestWithoutAssertion
from .ogc223_pass_in_test_handler import PassInTestHandler

#: One instance of every rule, in code order. Rules hold no state.
ALL_RULES: tuple[Rule, ...] = (
    IdAsKey(),
    GlInDel(),
    WorkAtImport(),
    UnreasonedSuppression(),
    SkipInExcept(),
    TestWithoutAssertion(),
    PassInTestHandler(),
)

#: Each rule by its code.
RULES: dict[str, Rule] = {rule.code: rule for rule in ALL_RULES}

__all__ = ['ALL_RULES', 'RULES', 'Invalid', 'Rule', 'snippet']
