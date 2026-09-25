"""The shape every rule has.

A rule is a class with a code, a short name, a docstring saying what it flags,
why, and what to use instead, and examples of both kinds: `VALID` snippets
that it must not report and `INVALID` ones it must report on the lines they
name. The test suite runs every rule's examples.

A rule reports through one or both of two methods. `visit` is handed each node
of a type named in `nodes`, from one walk of the tree shared by every rule;
`check_module` is called once per module, for a rule that reads something other
than nodes (the comments, say). A rule with a `scope` runs only on modules the
configuration places in that scope, and a rule with an `exempt_scope` runs on
every module but those.
"""

from __future__ import annotations

import ast
import dataclasses
import textwrap
from collections.abc import Iterator
from typing import TYPE_CHECKING, ClassVar

from ..findings import Finding

if TYPE_CHECKING:
    from ..engine import Module


def snippet(text: str) -> str:
    """An example's source: dedented, starting at its first line."""
    return textwrap.dedent(text).lstrip('\n')


@dataclasses.dataclass(frozen=True)
class Invalid:
    """An example a rule must report, and the lines it must report it on."""

    source: str
    lines: tuple[int, ...]


class Rule:
    """A check with a stable code."""

    code: ClassVar[str]
    name: ClassVar[str]
    #: The configured scope a module must be in for this rule to run, or None.
    scope: ClassVar[str | None] = None
    #: The configured scope whose modules this rule does not run on, or None.
    exempt_scope: ClassVar[str | None] = None
    #: The node types `visit` is handed.
    nodes: ClassVar[tuple[type[ast.AST], ...]] = ()
    VALID: ClassVar[tuple[str, ...]] = ()
    INVALID: ClassVar[tuple[Invalid, ...]] = ()

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:  # noqa: ARG002 the base reports nothing
        """Findings for one node of a type in `nodes`."""
        yield from ()

    def check_module(self, module: Module) -> Iterator[Finding]:  # noqa: ARG002 the base reports nothing
        """Findings for the module as a whole."""
        yield from ()

    def finding(self, where: ast.AST | int, message: str) -> Finding:
        """A finding of this rule at a node, or at the start of a line."""
        if isinstance(where, int):
            return Finding(where, 1, self.code, message)
        return Finding(
            getattr(where, 'lineno', 1), getattr(where, 'col_offset', 0) + 1, self.code, message
        )
