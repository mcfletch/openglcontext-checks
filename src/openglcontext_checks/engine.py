"""Running rules over one module's source.

`parse_module` turns source bytes into a `Module`: its syntax tree, the symbol
table over it, and its suppression comments. `run_rules` walks the tree once,
handing each node to the rules that asked for its type, and drops the findings
a reasoned `# noqa` names. `check_source` is both for a string of source.
"""

from __future__ import annotations

import ast
import dataclasses
import tokenize
import warnings
from collections.abc import Iterable, Mapping, Sequence

from .findings import Finding
from .pragmas import Pragma, read_pragmas
from .rules import ALL_RULES, Rule
from .symbols import Symbols


class ParseError(Exception):
    """Source that is not Python this interpreter can parse."""

    def __init__(self, path: str, line: int, column: int, message: str) -> None:
        super().__init__('%s:%d:%d: cannot parse: %s' % (path, line, column, message))
        self.path = path
        self.line = line
        self.column = column
        self.message = message

    def __reduce__(self) -> tuple[type[ParseError], tuple[str, int, int, str]]:
        """Rebuilt from its fields, so a worker process can hand one back."""
        return ParseError, (self.path, self.line, self.column, self.message)


@dataclasses.dataclass(frozen=True)
class Module:
    """One module as the rules see it."""

    path: str
    tree: ast.Module
    symbols: Symbols
    pragmas: tuple[Pragma, ...]
    #: The configured scopes this module is in (`test`, ...).
    scopes: frozenset[str]
    #: Rule code to the project's own sanctioned names, where it names any.
    sanctioned: Mapping[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)


def parse_module(
    source: bytes,
    path: str,
    scopes: frozenset[str] = frozenset(),
    sanctioned: Mapping[str, tuple[str, ...]] | None = None,
) -> Module:
    """`source` parsed for the rules; raises `ParseError`."""
    try:
        with warnings.catch_warnings():
            # An invalid escape sequence and the like are the checked module's
            # business; the tree is the same with or without the warning.
            warnings.simplefilter('ignore')
            tree = ast.parse(source, filename=path)
        pragmas = read_pragmas(source)
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        # A null byte is a ValueError from `ast` before Python 3.12 and a
        # SyntaxError from it after; the position is there when one is known.
        line = getattr(error, 'lineno', None) or 1
        column = getattr(error, 'offset', None) or 1
        message = getattr(error, 'msg', None) or str(error)
        raise ParseError(path, line, column, message) from error
    return Module(path, tree, Symbols(tree), tuple(pragmas), scopes, dict(sanctioned or {}))


def run_rules(module: Module, rules: Sequence[Rule]) -> list[Finding]:
    """The findings of `rules` in `module`, less what is suppressed, in order."""
    active = [
        rule
        for rule in rules
        if (rule.scope is None or rule.scope in module.scopes)
        and rule.exempt_scope not in module.scopes
    ]
    found: set[Finding] = set()
    dispatch: dict[type[ast.AST], list[Rule]] = {}
    for rule in active:
        found.update(rule.check_module(module))
        for node_type in rule.nodes:
            dispatch.setdefault(node_type, []).append(rule)
    if dispatch:
        for node in module.symbols.nodes:
            for rule in dispatch.get(type(node), ()):
                found.update(rule.visit(node, module))
    by_line: dict[int, list[Pragma]] = {}
    for pragma in module.pragmas:
        by_line.setdefault(pragma.line, []).append(pragma)
    return sorted(
        finding
        for finding in found
        if not any(pragma.suppresses(finding.code) for pragma in by_line.get(finding.line, ()))
    )


def check_source(
    source: str | bytes,
    path: str = '<string>',
    *,
    codes: Iterable[str] | None = None,
    scopes: Iterable[str] = (),
    sanctioned: Mapping[str, tuple[str, ...]] | None = None,
) -> list[Finding]:
    """The findings of the rules `codes` (default every rule) in `source`."""
    data = source.encode('utf-8') if isinstance(source, str) else source
    wanted = None if codes is None else set(codes)
    rules = [rule for rule in ALL_RULES if wanted is None or rule.code in wanted]
    return run_rules(parse_module(data, path, frozenset(scopes), sanctioned), rules)
