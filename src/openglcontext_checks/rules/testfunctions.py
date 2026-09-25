"""What the test-scope rules count as a test function."""

from __future__ import annotations

import ast

from ..symbols import Symbols


def is_test_function(node: ast.FunctionDef | ast.AsyncFunctionDef, symbols: Symbols) -> bool:
    """Whether pytest collects `node` as a test.

    Named `test*`, as pytest's default `python_functions` has it, at module
    level or as a method of a module-level class.
    """
    if not node.name.startswith('test'):
        return False
    parent = symbols.parent(node)
    if isinstance(parent, ast.ClassDef):
        parent = symbols.parent(parent)
    return isinstance(parent, ast.Module)
