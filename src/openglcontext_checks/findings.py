"""What a rule reports."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, order=True)
class Finding:
    """One report: where in a module, which rule, and what to do about it."""

    line: int
    #: 1-based, as editors and ruff count.
    column: int
    code: str
    message: str

    def format(self, path: str) -> str:
        """The finding as `path:line:column: CODE message`."""
        return '%s:%d:%d: %s %s' % (path, self.line, self.column, self.code, self.message)
