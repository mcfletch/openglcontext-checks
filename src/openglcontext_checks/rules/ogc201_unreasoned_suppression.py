"""OGC201: a suppression without a reason."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from ..pragmas import NOQA, TYPE_IGNORE
from .base import Invalid, Rule, snippet

if TYPE_CHECKING:
    from ..engine import Module


class UnreasonedSuppression(Rule):
    """A `# noqa` or `# type: ignore` that does not say why.

    A suppression is a decision that a tool's report is wrong or does not
    matter on this line. Without the reason, the next reader cannot tell a
    judgement from a way of making a gate pass, and cannot tell when the
    reason has gone away. A bare pragma (`# noqa`, `# type: ignore` with no
    codes) is worse: it silences every report on the line, including ones
    nobody has seen.

    Reported: a `# noqa` or `# type: ignore` that names no code, and one that
    names codes with no reason after them. A `# noqa`'s reason is at least
    one word after the codes, optionally led by `-`, `--`, `:` or a dash. A
    `# type: ignore`'s reason goes in a comment of its own after it
    (`# type: ignore[attr-defined]  # the stubs lack it`), since mypy reports
    any other text after the codes as an invalid comment; text written there
    is reported too. A plain comment straight after a `# noqa` also counts.
    Pragmas are read from comments only, so text in a string is never one.

    Use instead: `# noqa: E501 a URL that cannot be broken`,
    `# type: ignore[attr-defined]  # numpy's stubs lack it`. For the OGC
    rules a reason is also what makes the `# noqa` suppress at all.
    """

    code = 'OGC201'
    name = 'suppression without a reason'

    VALID = (
        snippet("""
            other = compute()  # type: ignore[attr-defined]  # the stubs lack it
            line = 'x' * 200  # noqa: E501 a URL that cannot be broken
            text = '# noqa'
            # the noqa rules are described in the README
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                import os  # noqa: F401
                x = f()  # type: ignore[attr-defined]
                y = g()  # type: ignore
                z = h()  # noqa
                w = k()  # type: ignore[x]  # noqa: E501
                v = m()  # type: ignore[attr-defined] the stubs lack it
            """),
            (1, 2, 3, 4, 5, 5, 6),
        ),
    )

    def check_module(self, module: Module) -> Iterator[Finding]:
        for pragma in module.pragmas:
            if not pragma.codes:
                yield Finding(
                    pragma.line,
                    pragma.column,
                    self.code,
                    'bare # %s names no code and silences everything on the line; name the '
                    'codes it is for and the reason' % (pragma.kind,),
                )
            elif pragma.kind == TYPE_IGNORE and pragma.trailing:
                yield Finding(
                    pragma.line,
                    pragma.column,
                    self.code,
                    'mypy rejects text after # type: ignore[%s] as an invalid comment; put '
                    'the reason after a second #' % (', '.join(pragma.codes),),
                )
            elif not pragma.reason:
                if pragma.kind == NOQA:
                    written = '# noqa: %s' % (', '.join(pragma.codes),)
                else:
                    written = '# type: ignore[%s]' % (', '.join(pragma.codes),)
                yield Finding(
                    pragma.line,
                    pragma.column,
                    self.code,
                    '%s gives no reason; say why after the codes' % (written,),
                )
