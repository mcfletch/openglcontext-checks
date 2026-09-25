"""A mypy plugin: a checked type is made only by the module that checks it.

A checked type is a value whose type says a check has been made: a path the
resolver held to its document's directory, a URL put to a redirect policy, the
handle of the GL context that is current. Its constructor is private to the
module that makes the check, so a value of the type is proof the check ran,
and a function that takes one cannot be handed an unchecked value. mypy alone
accepts a construction written anywhere; this plugin reports one outside the
home module (the module defining the class), and a subclass declared outside
it, with the error code `checked-construction`.

In a module in the project's `loader` scope it also reports a file opened at
a path whose type is not one of the contained paths (`open`, `io.open`,
`PIL.Image.open`, `numpy.load` and the other openers OGC111 reads), with the
error code `unchecked-open`. A literal path, a file descriptor and an open
file are accepted; a `str`, `bytes`, a `pathlib.Path` or an `Any` is not.

Enabled by one line of a project's mypy configuration::

    [tool.mypy]
    plugins = ["openglcontext_checks.mypy_plugin"]

OpenGLContext's checked types (:data:`CHECKED_TYPES`) are refused in every
project. A project adds its own in `[tool.openglcontext-checks]` as
`checked-types`, and names the ones a loader may open as `contained-paths`;
the `loader` scope is read from the same table. The configuration is the one
beside mypy's own configuration file, or in the directory mypy runs in.

Where mypy has a hook of its own for a call this plugin reads, that hook
still decides the call's type: the plugin reports, and hands the call on.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

from mypy.errorcodes import ErrorCode
from mypy.messages import format_type
from mypy.nodes import StrExpr, TypeInfo
from mypy.options import Options
from mypy.plugin import ClassDefContext, FunctionContext, Plugin, ReportConfigContext
from mypy.plugins.default import DefaultPlugin
from mypy.types import AnyType, Instance, Type, UnionType, get_proper_type

from .config import Config, load_config

#: OpenGLContext's checked types, refused outside their home module in every project.
CHECKED_TYPES = (
    'OpenGLContext.loaders.resolver.ContainedPath',
    'OpenGLContext.loaders.resolver.CheckedURL',
    'OpenGLContext.contextresources.ContextKey',
)

#: OpenGLContext's checked types that name a file a loader may open.
CONTAINED_PATHS = ('OpenGLContext.loaders.resolver.ContainedPath',)

#: The calls that open a file by path, as OGC111 reads them.
OPENERS = frozenset(
    {
        'builtins.open',
        'io.open',
        '_io.open',
        'codecs.open',
        'gzip.open',
        'bz2.open',
        'lzma.open',
        'tarfile.open',
        'zipfile.ZipFile',
        'PIL.Image.open',
        'numpy.load',
        'numpy.fromfile',
    }
)

#: The types an opener reads as a path, rather than as a descriptor or a file.
_PATH_TYPES = ('builtins.str', 'builtins.bytes', 'os.PathLike')

CHECKED_CONSTRUCTION = ErrorCode(
    'checked-construction',
    'A checked type made or subclassed outside the module that checks it',
    'openglcontext-checks',
)
UNCHECKED_OPEN = ErrorCode(
    'unchecked-open',
    'A loader opens a path nothing has contained',
    'openglcontext-checks',
)

_Hook = Callable[[FunctionContext], Type]


class CheckedTypesPlugin(Plugin):
    """Refuses a checked type made outside its home, and an unchecked open in a loader."""

    def __init__(self, options: Options) -> None:
        super().__init__(options)
        start = os.path.dirname(os.path.abspath(options.config_file or 'pyproject.toml'))
        self.config: Config = load_config(start)
        self.checked = frozenset(CHECKED_TYPES + self.config.checked_types)
        self.contained = tuple(CONTAINED_PATHS + self.config.contained_paths)
        self._default = DefaultPlugin(options)

    def report_config_data(self, ctx: ReportConfigContext) -> object:
        """What decides a module's findings, so a changed setting checks it again."""
        return {
            'checked': sorted(self.checked),
            'contained': list(self.contained),
            'loader': self._in_loader_scope(ctx.path),
        }

    def get_function_hook(self, fullname: str) -> _Hook | None:
        if fullname in self.checked:
            return self._chained(fullname, self._refuse_construction)
        if fullname in OPENERS:
            return self._chained(fullname, self._refuse_unchecked_open)
        return None

    def get_base_class_hook(self, fullname: str) -> Callable[[ClassDefContext], None] | None:
        if fullname in self.checked:
            return self._refuse_subclass
        return None

    def _chained(self, fullname: str, check: Callable[[FunctionContext, str], None]) -> _Hook:
        """`check`, then the type mypy's own hook for `fullname` gives, if it has one."""
        default = self._default.get_function_hook(fullname)

        def hook(ctx: FunctionContext) -> Type:
            check(ctx, fullname)
            return default(ctx) if default is not None else ctx.default_return_type

        return hook

    def _refuse_construction(self, ctx: FunctionContext, _fullname: str) -> None:
        made = get_proper_type(ctx.default_return_type)
        assert isinstance(made, Instance)
        info = made.type
        assert self._modules is not None
        home = self._modules[info.module_name]
        if os.path.abspath(ctx.api.path) != os.path.abspath(home.path):
            ctx.api.fail(
                '%s is made only by %s, where the value is checked; call the function there'
                ' that checks it and returns one' % (info.fullname, info.module_name),
                ctx.context,
                code=CHECKED_CONSTRUCTION,
            )

    def _refuse_subclass(self, ctx: ClassDefContext) -> None:
        for base in ctx.cls.info.mro[1:]:
            if base.fullname in self.checked and base.module_name != ctx.api.cur_mod_id:
                ctx.api.fail(
                    '%s is subclassed only in %s, where its values are checked'
                    % (base.fullname, base.module_name),
                    ctx.cls,
                    code=CHECKED_CONSTRUCTION,
                )
                return

    def _refuse_unchecked_open(self, ctx: FunctionContext, fullname: str) -> None:
        if not ctx.args or not ctx.args[0] or not self._in_loader_scope(ctx.api.path):
            return
        if isinstance(ctx.args[0][0], StrExpr):
            return
        for kind in _alternatives(ctx.arg_types[0][0]):
            if self._unchecked(kind):
                ctx.api.fail(
                    '%s() is handed a path of type %s, which nothing has contained; in a'
                    ' loader module a file is opened at a contained path (%s)'
                    % (
                        fullname.removeprefix('builtins.'),
                        format_type(ctx.arg_types[0][0], ctx.api.options),
                        ', '.join(self.contained),
                    ),
                    ctx.context,
                    code=UNCHECKED_OPEN,
                )
                return

    def _unchecked(self, kind: Type) -> bool:
        """Whether an opener handed `kind` opens a path nothing contained."""
        proper = get_proper_type(kind)
        if isinstance(proper, AnyType):
            return True
        if not isinstance(proper, Instance):
            return False
        info: TypeInfo = proper.type
        if any(info.has_base(name) for name in self.contained):
            return False
        return any(info.has_base(name) for name in _PATH_TYPES)

    def _in_loader_scope(self, path: str) -> bool:
        relative = os.path.relpath(os.path.abspath(path), self.config.root).replace(os.sep, '/')
        return 'loader' in self.config.scopes_for(relative)


def _alternatives(kind: Type) -> Iterator[Type]:
    """Each type a value of `kind` may be: the items of a union, or `kind` itself."""
    proper = get_proper_type(kind)
    if isinstance(proper, UnionType):
        for item in proper.items:
            yield from _alternatives(item)
    else:
        yield proper


def plugin(_version: str) -> type[Plugin]:
    """The plugin mypy loads: the same one for every version of mypy it runs under."""
    return CheckedTypesPlugin
