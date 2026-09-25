"""The rules, by code."""

from __future__ import annotations

from .base import Invalid, Rule, snippet

#: One instance of every rule, in code order. Rules hold no state.
ALL_RULES: tuple[Rule, ...] = ()

#: Each rule by its code.
RULES: dict[str, Rule] = {rule.code: rule for rule in ALL_RULES}

__all__ = ['ALL_RULES', 'RULES', 'Invalid', 'Rule', 'snippet']
