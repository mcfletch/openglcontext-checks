"""OGC232: an override that renames an inherited parameter.

`Index` resolves a class's bases through its module's imports, reading a
module from disk when a base is defined there, and `find_overrides` uses it to
report each renamed parameter. `OverrideRenamesParam` turns those into findings.
"""

from __future__ import annotations

import ast
import dataclasses
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet

if TYPE_CHECKING:
    from ..engine import Module


class OverrideRenamesParam(Rule):
    """A subclass overrides a method but renames an inherited parameter with `_`.

    An override replaces the base class's method, so the base's parameter names
    are part of the interface: a caller reaching the base by keyword, and a
    type checker reading the base's signature, both use them. A subclass that
    writes `def method(self, _over, _now)` where the base wrote
    `def method(self, over, now)` changes those names, and only an underscore
    has been added to the ones it does not read. The unused-argument warning
    the underscore silences is answered instead by keeping the base's names and
    naming the suppressed code with a reason.

    Bases are resolved through the classes' modules and their imports: a base
    defined in another module of the project is read from disk and its method
    compared, so a cross-file override is reported too. Only a parameter whose
    only change is a leading `_` is reported; a rename that is not an
    underscore prefix, and a class whose base is outside the project or is not
    a class, are not.

    Use instead: keep the base's parameter names on the override, and silence
    an unused-argument warning on it by name with a reason
    (`# noqa: ARG002 the base's signature is kept`).
    """

    code = 'OGC232'
    name = 'override renames inherited parameter'

    VALID = (
        snippet("""
            class Base:
                def method(self, over, now):
                    pass

            class Child(Base):
                def method(self, over, now):
                    pass
        """),
        snippet("""
            class Base:
                def method(self, over):
                    pass

            class Child(Base):
                def method(self, over, extra):
                    pass
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                class Base:
                    def method(self, over, now):
                        pass

                class Child(Base):
                    def method(self, _over, _now):
                        pass
            """),
            (6,),
        ),
    )

    def check_module(self, module: Module) -> Iterator[Finding]:
        """Each override in `module` that renames an inherited parameter."""
        index = Index([module], reads=module.reads)
        shown = {module.path: module.path}
        classes = [info for info in index.classes.values() if info.module is module]
        for override in find_overrides(index, shown, classes=classes):
            names = ', '.join('%s -> %s' % (item.base, item.child) for item in override.renamed)
            yield Finding(
                override.child_line,
                override.child_column,
                self.code,
                '%s overrides %s: %s' % (override.child_name, override.base_name, names),
            )


#: A method definition, sync or async.
Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclasses.dataclass(frozen=True)
class Renamed:
    """One inherited parameter renamed by an override."""

    base: str
    child: str


@dataclasses.dataclass(frozen=True)
class Override:
    """An override that renames at least one inherited parameter."""

    #: The subclass's path, line and column, and the class and method names.
    child_path: str
    child_line: int
    child_column: int
    child_name: str
    #: The base method's path and line, and the class and method names.
    base_path: str
    base_line: int
    base_name: str
    renamed: tuple[Renamed, ...]


@dataclasses.dataclass
class ClassInfo:
    """A class definition the index resolved, and its immediate bases."""

    module: Module
    #: The class's dotted path within the module (`Outer.Inner`).
    name: str
    node: ast.ClassDef
    #: The dotted module name (`vrml.x3d.pointing`).
    module_dotted: str
    #: The bases as written, before resolution.
    bases: tuple[ast.expr, ...]
    #: Each method defined directly in the class body, by name.
    methods: dict[str, Function]
    #: Each class defined directly in this class body, by name.
    nested: dict[str, ClassInfo] = dataclasses.field(default_factory=dict)

    @property
    def dotted(self) -> str:
        """The class's fully dotted name."""
        return '%s.%s' % (self.module_dotted, self.name) if self.name else self.module_dotted

    def method_location(self, method: str) -> tuple[str, int]:
        """The file path and line the class defines `method` at."""
        return self.module.path, self.methods[method].lineno


def dotted_module_name(path: str) -> str:
    """The dotted module name of a `.py` file, from its package directories."""
    directory, filename = os.path.split(path)
    stem = filename[:-3] if filename.endswith('.py') else filename
    parts: list[str] = []
    if stem == '__init__':
        parts.append(os.path.basename(directory))
        directory = os.path.dirname(directory)
    else:
        parts.append(stem)
    while os.path.isfile(os.path.join(directory, '__init__.py')):
        parts.append(os.path.basename(directory))
        directory = os.path.dirname(directory)
    return '.'.join(reversed(parts))


def _definitions(body: Sequence[ast.stmt]) -> Iterator[tuple[str, Function]]:
    """Each method name and node defined directly in a class body."""
    for statement in body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            yield statement.name, statement


class Index:
    """Every class of the parsed modules, resolved through their imports.

    A base whose module is not among `sources` is read from disk on demand:
    `find` maps a dotted module name to a file path, and its file is parsed and
    indexed the first time a name in it is looked up. With no `find`, the
    imports are searched beside the modules already given, so an index built
    over one module can resolve a base in another module of the same project.
    """

    def __init__(
        self,
        sources: Iterable[Module],
        find: Callable[[str], str | None] | None = None,
        reads: set[str] | None = None,
    ) -> None:
        self.modules: dict[str, Module] = {}
        self.is_package: dict[str, bool] = {}
        self.classes: dict[str, ClassInfo] = {}
        self.by_module: dict[str, dict[str, ClassInfo]] = {}
        self._bases: dict[str, tuple[ClassInfo, ...]] = {}
        self._find = find
        self._reads = reads if reads is not None else set()
        self._directories: list[str] = []
        self._searched: set[str] = set()
        for module in sources:
            self._index(module)

    def _index(self, module: Module) -> str:
        """Add `module` and its classes to the index; the module's dotted name."""
        directory = os.path.dirname(os.path.abspath(module.path))
        if directory not in self._directories:
            self._directories.append(directory)
        dotted = dotted_module_name(module.path)
        self.modules[dotted] = module
        self.is_package[dotted] = os.path.basename(module.path) == '__init__.py'
        self._collect(module, dotted, '', module.tree.body)
        return dotted

    def _collect(
        self,
        module: Module,
        module_dotted: str,
        prefix: str,
        body: Sequence[ast.stmt],
        parent: ClassInfo | None = None,
    ) -> None:
        """Index each class in `body`, and recurse into the ones it holds."""
        for statement in body:
            if not isinstance(statement, ast.ClassDef):
                continue
            name = prefix + statement.name
            info = ClassInfo(
                module=module,
                name=name,
                node=statement,
                module_dotted=module_dotted,
                bases=tuple(statement.bases),
                methods=dict(_definitions(statement.body)),
            )
            self.classes[info.dotted] = info
            self.by_module.setdefault(module_dotted, {})[name] = info
            if parent is not None:
                parent.nested[statement.name] = info
            self._collect(module, module_dotted, name + '.', statement.body, info)

    def resolve(self, base: ast.expr, owner: ClassInfo) -> ClassInfo | None:
        """The class `base` names in `owner`'s scope, or None if it is not ours."""
        if isinstance(base, ast.Name):
            local = self.by_module.get(owner.module_dotted, {}).get(base.id)
            if local is not None:
                return local
            qualified = owner.module.symbols.qualified_name(base)
            if qualified is not None:
                return self._lookup(qualified, owner)
            return self._from_star(base.id, owner)
        if isinstance(base, ast.Attribute):
            qualified = owner.module.symbols.qualified_name(base)
            if qualified is not None:
                return self._lookup(qualified, owner)
            parent = self.resolve(base.value, owner)
            if parent is not None:
                return parent.nested.get(base.attr)
        return None

    def _lookup(self, qualified: str, owner: ClassInfo) -> ClassInfo | None:
        """The class a dotted name names, resolving a relative import."""
        absolute = self._absolute(qualified, owner)
        found = self.classes.get(absolute)
        if found is not None:
            return found
        self._load(absolute)
        found = self.classes.get(absolute)
        if found is not None:
            return found
        head, _, tail = absolute.rpartition('.')
        if head:
            self._load(head)
            return self.by_module.get(head, {}).get(tail)
        return None

    def _load(self, qualified: str) -> None:
        """Index the module holding `qualified`, read from disk, once."""
        parts = qualified.split('.')
        for split in range(len(parts) - 1, 0, -1):
            module_name = '.'.join(parts[:split])
            if module_name in self._searched:
                continue
            self._searched.add(module_name)
            path = self._find_module(module_name)
            if path is None:
                continue
            module = self._reader(path)
            if module is not None:
                self._index(module)
            return

    def _find_module(self, module_name: str) -> str | None:
        """The file naming `module_name`, searched beside the indexed modules."""
        if self._find is not None:
            return self._find(module_name)
        parts = module_name.split('.')
        for directory in self._directories:
            while True:
                candidate = os.path.join(directory, *parts)
                for path in (candidate + '.py', os.path.join(candidate, '__init__.py')):
                    if os.path.isfile(path):
                        return path
                parent = os.path.dirname(directory)
                if parent == directory:
                    break
                directory = parent
        return None

    def _reader(self, path: str) -> Module | None:
        """`path` parsed as a module, or None if it cannot be read or parsed."""
        from ..engine import (  # noqa: PLC0415 delayed to break the import cycle
            ParseError,
            parse_module,
        )

        try:
            with open(path, 'rb') as handle:
                content = handle.read()
        except OSError:
            return None
        self._reads.add(path)
        try:
            return parse_module(content, path)
        except ParseError:
            return None

    def _absolute(self, qualified: str, owner: ClassInfo) -> str:
        """`qualified` with a leading `from . import` marker resolved to a package."""
        if not qualified.startswith('.'):
            return qualified
        level = len(qualified) - len(qualified.lstrip('.'))
        rest = qualified[level:]
        parts = owner.module_dotted.split('.')
        if not self.is_package.get(owner.module_dotted, False):
            parts = parts[:-1]
        drop = level - 1
        if drop:
            parts = parts[: len(parts) - drop] if drop <= len(parts) else []
        base = '.'.join(parts)
        return '%s.%s' % (base, rest) if base else rest

    def _from_star(self, name: str, owner: ClassInfo) -> ClassInfo | None:
        """The one class named `name` among `owner`'s star imports, if there is one."""
        found: set[str] = set()
        classes: list[ClassInfo] = []
        for dotted in owner.module.symbols.star_modules(owner.node):
            absolute = self._absolute(dotted, owner)
            match = self.by_module.get(absolute, {}).get(name)
            if match is not None and match.dotted not in found:
                found.add(match.dotted)
                classes.append(match)
        return classes[0] if len(classes) == 1 else None

    def resolved_bases(self, info: ClassInfo) -> tuple[ClassInfo, ...]:
        """The bases of `info` that resolve to a class of the project."""
        if info.dotted not in self._bases:
            self._bases[info.dotted] = tuple(
                base
                for base in (self.resolve(item, info) for item in info.bases)
                if base is not None
            )
        return self._bases[info.dotted]

    def linearization(self, info: ClassInfo, seen: frozenset[str] = frozenset()) -> list[ClassInfo]:
        """`info` and its project bases in method-resolution order."""
        if info.dotted in seen:
            return []
        seen = seen | {info.dotted}
        parents = self.resolved_bases(info)
        sequences = [self.linearization(parent, seen) for parent in parents]
        sequences.append(list(parents))
        result = [info]
        while any(sequences):
            head = self._next_head(sequences)
            if head is None:
                for sequence in sequences:
                    for item in sequence:
                        if item not in result:
                            result.append(item)
                break
            result.append(head)
            for sequence in sequences:
                if sequence and sequence[0] is head:
                    sequence.pop(0)
        return result

    @staticmethod
    def _next_head(sequences: Sequence[list[ClassInfo]]) -> ClassInfo | None:
        """The first linearization head no other sequence holds behind its own."""
        for sequence in sequences:
            if not sequence:
                continue
            candidate = sequence[0]
            if all(candidate not in other[1:] for other in sequences):
                return candidate
        return None


def _parameters(
    func: Function,
) -> tuple[list[ast.arg], list[ast.arg], ast.arg | None, ast.arg | None]:
    """A function's positional, keyword-only, vararg and kwarg arguments."""
    args = func.args
    return list(args.posonlyargs) + list(args.args), list(args.kwonlyargs), args.vararg, args.kwarg


def _renamed(base: ast.arg | None, child: ast.arg | None) -> Renamed | None:
    """The rename when `child` is `base`'s name with an underscore, else None."""
    if base is None or child is None:
        return None
    if base.arg.startswith('_') or child.arg != '_' + base.arg:
        return None
    return Renamed(base.arg, child.arg)


def renamed_parameters(child: Function, base: Function) -> tuple[Renamed, ...]:
    """Each parameter `child` renames from `base` with a leading underscore."""
    child_positional, child_kwonly, child_vararg, child_kwarg = _parameters(child)
    base_positional, base_kwonly, base_vararg, base_kwarg = _parameters(base)
    pairs: list[tuple[ast.arg | None, ast.arg | None]] = list(
        zip(base_positional, child_positional, strict=False)
    )
    pairs += list(zip(base_kwonly, child_kwonly, strict=False))
    pairs += [(base_vararg, child_vararg), (base_kwarg, child_kwarg)]
    return tuple(
        item for item in (_renamed(base_arg, child_arg) for base_arg, child_arg in pairs) if item
    )


def find_overrides(
    index: Index,
    shown: Mapping[str, str],
    classes: Iterable[ClassInfo] | None = None,
) -> list[Override]:
    """Every method of `classes` (default every indexed class) that renamed a base's."""
    found: list[Override] = []
    for info in list(index.classes.values()) if classes is None else classes:
        for method, child in info.methods.items():
            for definer in index.linearization(info)[1:]:
                base = definer.methods.get(method)
                if base is None:
                    continue
                renamed = renamed_parameters(child, base)
                if not renamed:
                    continue
                base_path, base_line = definer.method_location(method)
                found.append(
                    Override(
                        child_path=shown.get(info.module.path, info.module.path),
                        child_line=child.lineno,
                        child_column=child.col_offset + 1,
                        child_name='%s.%s' % (info.name, method),
                        base_path=shown.get(base_path, base_path),
                        base_line=base_line,
                        base_name='%s.%s' % (definer.name, method),
                        renamed=renamed,
                    )
                )
                break
    found.sort(key=lambda item: (item.child_path, item.child_line, item.child_name))
    return found
