"""The suppression comments in a module: `# noqa` and `# type: ignore`.

Comments are read from the token stream, so a pragma spelled inside a string is
not one. A comment token can hold several pragmas (`# type: ignore[x]  # noqa:
E501 reason`); each `#` starts a segment, and a segment is a pragma when it
opens with `noqa` or `type: ignore`.

A `# noqa`'s reason is the text after its codes, with a leading `-`, `--`,
`:` or dash dropped. A `# type: ignore` has no reason of its own: mypy accepts
only whitespace or another `#` after one and reports anything else as an
invalid comment, so the text there is kept as `trailing` instead. For either
kind, where the reason is empty, a plain comment segment straight after it is
the reason, which is the `# type: ignore[code]  # why` form mypy's own
documentation uses.

`# noqa` takes the codes ruff does (letters then digits, separated by commas
or spaces), so one comment serves both tools: `# noqa: E501, OGC131 reason`.
"""

from __future__ import annotations

import dataclasses
import io
import re
import tokenize

NOQA = 'noqa'
TYPE_IGNORE = 'type: ignore'

# Each of these reads the inside of one comment token, never the source.
_NOQA = re.compile(r'noqa(?![\w-])(?P<colon>\s*:)?(?P<rest>.*)', re.IGNORECASE | re.DOTALL)
_NOQA_CODE = re.compile(r'\s*(?P<code>[A-Z]+[0-9]+)\b\s*,?')
_TYPE_IGNORE = re.compile(
    r'type:\s*ignore(?![\w-])(?:\[(?P<codes>[^\]]*)\])?(?P<rest>.*)', re.DOTALL
)
_WORD = re.compile(r'\w')
_LEAD = ' \t-:\u2014\u2013'


@dataclasses.dataclass(frozen=True)
class Pragma:
    """One suppression comment: what it is, where, what it names and why."""

    kind: str
    line: int
    #: 1-based, at the pragma's own `#`.
    column: int
    #: The codes it names, in the order written; empty for a bare pragma.
    codes: tuple[str, ...]
    #: The text giving the reason, or '' where there is none.
    reason: str
    #: Text written straight after the codes of a type-ignore pragma, which
    #: mypy rejects; always '' for a noqa.
    trailing: str = ''

    def suppresses(self, code: str) -> bool:
        """Whether this pragma suppresses an OGC finding of `code`.

        Only a `# noqa` that names the code and gives a reason does: a bare
        `# noqa` or an unreasoned one is itself a finding (OGC201).
        """
        return self.kind == NOQA and code in self.codes and bool(self.reason)


def read_pragmas(source: bytes) -> list[Pragma]:
    """Every pragma in `source`, in the order they appear.

    Raises `tokenize.TokenError` or `SyntaxError` for source that does not
    tokenize. Source without the bytes of either pragma has none, and is not
    tokenized.
    """
    if b'ignore' not in source and b'noqa' not in source.lower():
        return []
    found: list[Pragma] = []
    for token in tokenize.tokenize(io.BytesIO(source).readline):
        if token.type == tokenize.COMMENT:
            line, column = token.start
            found.extend(parse_comment(token.string, line, column + 1))
    return found


def parse_comment(text: str, line: int, column: int) -> list[Pragma]:
    """The pragmas in one comment token starting at `column` (1-based)."""
    hashes = [index for index, character in enumerate(text) if character == '#']
    segments = [
        (start, text[start + 1 : end])
        for start, end in zip(hashes, [*hashes[1:], len(text)], strict=True)
    ]
    parsed = [(start, _parse_segment(body.strip())) for start, body in segments]
    pragmas = []
    for index, (start, pragma) in enumerate(parsed):
        if pragma is None:
            continue
        kind, codes, reason, trailing = pragma
        if not reason and index + 1 < len(parsed) and parsed[index + 1][1] is None:
            following = segments[index + 1][1].strip(_LEAD)
            if _WORD.search(following):
                reason = following
        pragmas.append(Pragma(kind, line, column + start, codes, reason, trailing))
    return pragmas


def _parse_segment(segment: str) -> tuple[str, tuple[str, ...], str, str] | None:
    """(kind, codes, reason, trailing) where `segment` opens with a pragma, else None."""
    noqa = _NOQA.match(segment)
    if noqa:
        rest = noqa.group('rest')
        codes: list[str] = []
        if noqa.group('colon'):
            position = 0
            while code := _NOQA_CODE.match(rest, position):
                codes.append(code.group('code'))
                position = code.end()
            rest = rest[position:]
        return NOQA, tuple(codes), _reason(rest), ''
    ignore = _TYPE_IGNORE.match(segment)
    if ignore:
        listed = ignore.group('codes') or ''
        codes = [code.strip() for code in listed.split(',') if code.strip()]
        return TYPE_IGNORE, tuple(codes), '', ignore.group('rest').strip()
    return None


def _reason(rest: str) -> str:
    """The reason text in what follows a pragma's codes, or ''."""
    reason = rest.strip(_LEAD).strip()
    return reason if _WORD.search(reason) else ''
