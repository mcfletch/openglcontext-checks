"""The rules, by code."""

from __future__ import annotations

from .base import Invalid, Rule, snippet
from .ogc101_bare_document_conversion import BareDocumentConversion
from .ogc102_decode_before_size_check import DecodeBeforeSizeCheck
from .ogc111_unconfined_path import UnconfinedPath
from .ogc121_write_in_place import WriteInPlace
from .ogc131_id_key import IdAsKey
from .ogc141_gl_in_del import GlInDel
from .ogc151_gl_state_not_restored import GlStateNotRestored
from .ogc161_import_time import WorkAtImport
from .ogc201_unreasoned_suppression import UnreasonedSuppression
from .ogc221_skip_in_except import SkipInExcept
from .ogc222_test_without_assertion import TestWithoutAssertion
from .ogc223_pass_in_test_handler import PassInTestHandler

#: One instance of every rule, in code order. Rules hold no state.
ALL_RULES: tuple[Rule, ...] = (
    BareDocumentConversion(),
    DecodeBeforeSizeCheck(),
    UnconfinedPath(),
    WriteInPlace(),
    IdAsKey(),
    GlInDel(),
    GlStateNotRestored(),
    WorkAtImport(),
    UnreasonedSuppression(),
    SkipInExcept(),
    TestWithoutAssertion(),
    PassInTestHandler(),
)

#: Each rule by its code.
RULES: dict[str, Rule] = {rule.code: rule for rule in ALL_RULES}

__all__ = ['ALL_RULES', 'RULES', 'Invalid', 'Rule', 'snippet']
