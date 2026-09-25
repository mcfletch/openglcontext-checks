"""OGC161: configuration or I/O at import."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..findings import Finding
from .base import Invalid, Rule, snippet

if TYPE_CHECKING:
    from ..engine import Module
    from ..symbols import Symbols

#: Configuration read or written in any form.
_CONFIGURATION = frozenset({'os.environ', 'os.environb', 'sys.argv'})
#: Functions that read or change the process's configuration when called.
_CONFIGURING = frozenset(
    {
        'os.getenv',
        'os.getenvb',
        'os.putenv',
        'os.unsetenv',
        'locale.setlocale',
    }
)
#: Functions that do I/O when called.
_IO = frozenset(
    {
        'builtins.open',
        'io.open',
        'os.makedirs',
        'os.mkdir',
        'os.remove',
        'os.unlink',
        'os.rename',
        'os.replace',
        'os.chdir',
    }
)
#: Modules every function of which does I/O.
_IO_MODULES = ('shutil.', 'subprocess.')


class WorkAtImport(Rule):
    """The process's configuration read or changed, or I/O done, at import.

    A module-level or class-level statement runs when the module is first
    imported, which is before an application has parsed its arguments and
    before a test has set its environment. A value read then is frozen for the
    life of the process, and nothing can reach it afterwards; I/O done then
    runs for every importer, including one that only wanted a class from the
    module.

    The set is closed and exact:

    - read or written, in any form: `os.environ`, `os.environb`, `sys.argv`;
    - called: `os.getenv`, `os.getenvb`, `os.putenv`, `os.unsetenv`,
      `locale.setlocale`, `open` (the builtin, `io.open`), `os.makedirs`,
      `os.mkdir`, `os.remove`, `os.unlink`, `os.rename`, `os.replace`,
      `os.chdir`, and every function of `shutil` and `subprocess`.

    Names are resolved through imports, so `from os import environ` is
    `os.environ`. Import time here is module level and class-body level,
    including decorators and default values, which are evaluated there. The
    body of a function or lambda is not, nor the body of
    `if __name__ == '__main__':` or of `if TYPE_CHECKING:`.

    Use instead: read configuration where it is used, in a function the
    application calls; in OpenGLContext, `renderoptions.env_flag_once` and
    `env_number_once` read an environment variable once, on first use.
    """

    code = 'OGC161'
    name = 'configuration or I/O at import'
    nodes = (ast.Name, ast.Attribute)

    VALID = (
        snippet("""
            import os

            def backend():
                return os.environ.get('OPENGLCONTEXT_BACKEND', 'glfw')
        """),
        snippet("""
            import subprocess
            import sys

            if __name__ == '__main__':
                subprocess.run([sys.executable, '-V'])
                print(sys.argv)
        """),
        snippet("""
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                import os
                HOME = os.environ['HOME']
        """),
        snippet("""
            import os
            import subprocess

            PIPE = subprocess.PIPE
            SHADERS = os.path.join(os.path.dirname(__file__), 'shaders')
        """),
        snippet("""
            class Settings:
                def load(self):
                    with open(self.path) as handle:
                        return handle.read()
        """),
        snippet("""
            import os

            home = lambda: os.environ['HOME']
        """),
    )
    INVALID = (
        Invalid(
            snippet("""
                import os
                BACKEND = os.environ.get('OPENGLCONTEXT_BACKEND', 'glfw')
            """),
            (2,),
        ),
        Invalid(
            snippet("""
                from os import environ, getenv
                import sys
                DEBUG = getenv('DEBUG')
                environ['PYOPENGL_ERROR_CHECKING'] = '0'
                VERBOSE = '-v' in sys.argv
            """),
            (3, 4, 5),
        ),
        Invalid(
            snippet("""
                import json
                with open('settings.json') as handle:
                    SETTINGS = json.load(handle)
            """),
            (2,),
        ),
        Invalid(
            snippet("""
                import os, shutil, subprocess
                os.makedirs('cache', exist_ok=True)
                shutil.rmtree('old')
                VERSION = subprocess.check_output(['git', 'describe'])
            """),
            (2, 3, 4),
        ),
        Invalid(
            snippet("""
                import os
                class Config:
                    home = os.environ['HOME']
                    def path(self, root=os.getenv('ROOT')):
                        return root
            """),
            (3, 4),
        ),
        Invalid(
            snippet("""
                import locale, os
                locale.setlocale(locale.LC_ALL, '')
                if __name__ == '__main__':
                    pass
                else:
                    os.chdir('/')
            """),
            (2, 6),
        ),
    )

    def visit(self, node: ast.AST, module: Module) -> Iterator[Finding]:
        assert isinstance(node, ast.Name | ast.Attribute)
        symbols = module.symbols
        if not symbols.runs_at_import(node):
            return
        qualified = symbols.qualified_name(node)
        if qualified is None:
            return
        parent = symbols.parent(node)
        called = isinstance(parent, ast.Call) and parent.func is node
        if qualified in _CONFIGURATION or (called and qualified in _CONFIGURING):
            message = (
                'at import: the process configuration is read or changed before an '
                'application or test can set it; do it in a function, where it is used'
            )
        elif called and (qualified in _IO or qualified.startswith(_IO_MODULES)):
            message = (
                'at import: importing the module does I/O; do it in a function the '
                'application calls'
            )
        else:
            return
        if _guarded(node, symbols):
            return
        text = ast.unparse(node) + ('()' if called else '')
        yield self.finding(node, '%s %s' % (text, message))


def _guarded(node: ast.AST, symbols: Symbols) -> bool:
    """Whether `node` is in the body of a `__main__` or `TYPE_CHECKING` block."""
    child = node
    for ancestor in symbols.ancestors(node):
        if (
            isinstance(ancestor, ast.If)
            and any(child is statement for statement in ancestor.body)
            and (_is_main_guard(ancestor.test) or _is_type_checking(ancestor.test, symbols))
        ):
            return True
        child = ancestor
    return False


def _is_main_guard(test: ast.expr) -> bool:
    """Whether `test` is `__name__ == '__main__'`, either way round."""
    if not (
        isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
    ):
        return False
    sides = {ast.dump(test.left), ast.dump(test.comparators[0])}
    return sides == {
        ast.dump(ast.Name('__name__', ast.Load())),
        ast.dump(ast.Constant('__main__')),
    }


def _is_type_checking(test: ast.expr, symbols: Symbols) -> bool:
    """Whether `test` is `TYPE_CHECKING`, bare or from `typing`."""
    if isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING':
        return True
    qualified = symbols.qualified_name(test)
    return qualified is not None and qualified.endswith('.TYPE_CHECKING')
