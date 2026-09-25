"""The mypy plugin, run by mypy over small projects written for each case.

Each test writes a project (a `pyproject.toml` naming the plugin, and the
modules the case needs) and runs mypy over it in this process, so what is
asserted is what mypy reports to a user.
"""

import os
import textwrap

import pytest

api = pytest.importorskip('mypy.api', reason='the mypy plugin is tested by running mypy')

HOME = """
class Token(str):
    __slots__ = ()


class Contained(str):
    __slots__ = ()


def token(value: str) -> Token:
    return Token(value)


def contain(value: str) -> Contained:
    return Contained(value)


class Refined(Contained):
    __slots__ = ()
"""

TABLE = """
[tool.mypy]
plugins = ["openglcontext_checks.mypy_plugin"]

[tool.openglcontext-checks]
checked-types = ["home.Token", "home.Contained"]
contained-paths = ["home.Contained"]

[tool.openglcontext-checks.scopes]
loader = ["reader/**"]
"""


@pytest.fixture(scope='module')
def cache_dir(tmp_path_factory):
    """One mypy cache for the module's runs, so typeshed is read once."""
    return str(tmp_path_factory.mktemp('mypy-cache'))


@pytest.fixture
def project(tmp_path, monkeypatch, cache_dir):
    """Write `modules` (path to source) and a table; the messages mypy reports."""

    def run(modules, table=TABLE):
        (tmp_path / 'pyproject.toml').write_text(textwrap.dedent(table), encoding='utf-8')
        for name, source in {'home.py': HOME, **modules}.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source), encoding='utf-8')
        monkeypatch.chdir(tmp_path)
        out, err, _ = api.run(
            [
                '--config-file',
                str(tmp_path / 'pyproject.toml'),
                '--cache-dir',
                cache_dir,
                '--no-error-summary',
                '--show-error-codes',
                '--hide-error-context',
                *sorted(modules),
            ]
        )
        assert not err, err
        return [line.replace(os.sep, '/') for line in out.splitlines()]

    return run


def test_a_checked_type_made_outside_its_home_module_is_refused(project):
    found = project(
        {
            'elsewhere.py': """
                from home import Contained, Token, contain

                made = Token('ab')
                derived = Contained(contain('x') + '/y')
                given = contain('x')
            """
        }
    )
    assert found == [
        'elsewhere.py:4: error: home.Token is made only by home, where the value is checked;'
        ' call the function there that checks it and returns one  [checked-construction]',
        'elsewhere.py:5: error: home.Contained is made only by home, where the value is checked;'
        ' call the function there that checks it and returns one  [checked-construction]',
    ]


def test_the_home_module_makes_its_own_checked_types(project):
    assert project({'home.py': HOME}) == []


def test_a_checked_type_is_not_subclassed_outside_its_home_module(project):
    found = project(
        {
            'elsewhere.py': """
                from home import Contained

                class Mine(Contained):
                    pass
            """
        }
    )
    assert found == [
        'elsewhere.py:4: error: home.Contained is subclassed only in home, where its values'
        ' are checked  [checked-construction]'
    ]


def test_the_engines_checked_types_are_refused_with_no_configuration(project):
    resolver = """
        class ContainedPath(str):
            pass
    """
    found = project(
        {
            'OpenGLContext/__init__.py': '',
            'OpenGLContext/loaders/__init__.py': '',
            'OpenGLContext/loaders/resolver.py': resolver,
            'user.py': """
                from OpenGLContext.loaders.resolver import ContainedPath

                path = ContainedPath('../../etc/passwd')
            """,
        },
        table='[tool.mypy]\nplugins = ["openglcontext_checks.mypy_plugin"]\n',
    )
    assert [line.split(': error: ')[0] for line in found] == ['user.py:4']
    assert found[0].endswith('[checked-construction]')


def test_a_loader_opens_a_contained_path_a_literal_or_a_handle(project):
    found = project(
        {
            'reader/__init__.py': '',
            'reader/formats.py': """
                import io
                from typing import Literal

                from home import Contained, Refined, contain

                def read(path: Contained, refined: Refined, fd: int,
                         either: 'Contained | int', fixed: Literal['fixed.json']) -> None:
                    reveal_type(open(path, 'rb'))
                    open(refined)
                    open('fixed.json')
                    open(fixed)
                    open(fd)
                    open(either)
                    io.open(contain('x'))
            """,
        }
    )
    assert len(found) == 1
    assert found[0].startswith('reader/formats.py:9: note: Revealed type is')
    assert 'BufferedReader' in found[0]


def test_a_loader_does_not_open_a_path_nothing_contained(project):
    found = project(
        {
            'reader/__init__.py': '',
            'reader/formats.py': """
                import io
                import os
                from typing import Any

                from home import Contained, Token

                def read(name: str, base: Contained, anything: Any, token: Token,
                         either: 'Contained | str', data: bytes) -> None:
                    open(name)
                    open(os.path.join(base, 'x'))
                    open(anything)
                    io.open(token)
                    open(either)
                    open(file=data)
            """,
        }
    )
    assert [line.split(': error: ')[0] for line in found] == [
        'reader/formats.py:%d' % line for line in (10, 11, 12, 13, 14, 15)
    ]
    assert found[0].endswith(
        ' open() is handed a path of type "str", which nothing has contained; in a loader'
        ' module a file is opened at a contained path'
        ' (OpenGLContext.loaders.resolver.ContainedPath, home.Contained)  [unchecked-open]'
    )
    assert 'of type "Any"' in found[2]


def test_an_unchecked_open_keeps_the_type_open_gives(project):
    found = project(
        {
            'reader/__init__.py': '',
            'reader/formats.py': """
                def read(name: str) -> None:
                    reveal_type(open(name, 'rb'))
                    reveal_type(open(name, encoding='utf-8'))
            """,
        }
    )
    assert [line.split(': ', 2)[1] for line in found] == ['error', 'note', 'error', 'note']
    assert 'BufferedReader' in found[1]
    assert 'TextIOWrapper' in found[3]


def test_a_module_outside_the_loader_scope_opens_what_it_likes(project):
    assert project({'tool.py': 'def read(name: str) -> None:\n    open(name)\n'}) == []


def test_a_hook_mypy_has_for_the_same_call_still_decides_its_type(project):
    table = TABLE.replace('"home.Contained"]\ncontained', '"functools.partial"]\ncontained')
    found = project(
        {
            'elsewhere.py': """
                import functools

                def add(a: int, b: int) -> int:
                    return a + b

                reveal_type(functools.partial(add, 1))
            """
        },
        table=table,
    )
    assert len(found) == 2
    assert found[0].endswith('[checked-construction]')
    assert found[1].endswith('Revealed type is "functools.partial[int]"')


def test_a_changed_scope_is_checked_again_rather_than_answered_from_the_cache(project):
    modules = {'tool.py': 'def read(name: str) -> None:\n    open(name)\n'}
    assert project(modules) == []
    found = project(modules, table=TABLE.replace('"reader/**"', '"tool.py"'))
    assert [line.split(': error: ')[0] for line in found] == ['tool.py:2']


def test_a_signature_hook_mypy_has_for_an_opener_still_gives_the_signature(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from mypy.options import Options

    from openglcontext_checks.mypy_plugin import CheckedTypesPlugin

    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    assert CheckedTypesPlugin(Options()).get_function_signature_hook('builtins.len') is None
    refined = object()

    class Default:
        def get_function_signature_hook(self, fullname):
            return lambda _ctx: refined

    hook = CheckedTypesPlugin(Options(), Default()).get_function_signature_hook('builtins.open')
    context = SimpleNamespace(args=[], api=SimpleNamespace(path='x.py'))
    assert hook(context) is refined
