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
from collections.abc import Iterable, Sequence

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


@dataclasses.dataclass(frozen=True)
class Module:
    """One module as the rules see it."""

    path: str
    tree: ast.Module
    symbols: Symbols
    pragmas: tuple[Pragma, ...]
    #: The configured scopes this module is in (`test`, ...).
    scopes: frozenset[str]


def parse_module(source: bytes, path: str, scopes: frozenset[str] = frozenset()) -> Module:
    """`source` parsed for the rules; raises `ParseError`."""
    try:
        with warnings.catch_warnings():
            # An invalid escape sequence and the like are the checked module's
            # business; the tree is the same with or without the warning.
            warnings.simplefilter('ignore')
            tree = ast.parse(source, filename=path)
        pragmas = read_pragmas(source)
    except SyntaxError as error:
        raise ParseError(path, error.lineno or 1, error.offset or 1, error.msg) from error
    except (tokenize.TokenError, ValueError) as error:
        raise ParseError(path, 1, 1, str(error)) from error
    return Module(path, tree, Symbols(tree), tuple(pragmas), scopes)


def run_rules(module: Module, rules: Sequence[Rule]) -> list[Finding]:
    """The findings of `rules` in `module`, less what is suppressed, in order."""
    active = [rule for rule in rules if rule.scope is None or rule.scope in module.scopes]
    found: set[Finding] = set()
    dispatch: dict[type[ast.AST], list[Rule]] = {}
    for rule in active:
        found.update(rule.check_module(module))
        for node_type in rule.nodes:
            dispatch.setdefault(node_type, []).append(rule)
    if dispatch:
        for node in ast.walk(module.tree):
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
) -> list[Finding]:
    """The findings of the rules `codes` (default every rule) in `source`."""
    data = source.encode('utf-8') if isinstance(source, str) else source
    wanted = None if codes is None else set(codes)
    rules = [rule for rule in ALL_RULES if wanted is None or rule.code in wanted]
    return run_rules(parse_module(data, path, frozenset(scopes)), rules)
