"""`[tool.openglcontext-checks]`: finding it, reading it and refusing a bad one."""

import textwrap

import pytest

import openglcontext_checks.config as config_module
from openglcontext_checks.config import ConfigError, load_config
from openglcontext_checks.rules import RULES

EVERY_CODE = frozenset(RULES)


def _project(tmp_path, table, name='pyproject.toml'):
    (tmp_path / name).write_text(textwrap.dedent(table), encoding='utf-8')
    return tmp_path


def test_a_project_with_no_table_gets_every_rule_and_the_default_scopes(tmp_path):
    _project(tmp_path, '[project]\nname = "x"\n')
    config = load_config(str(tmp_path))
    assert config.root == str(tmp_path)
    assert config.selected == tuple(sorted(EVERY_CODE))
    assert config.paths == ('.',)
    assert config.scopes_for('tests/unit/test_a.py') == frozenset({'test'})
    assert config.scopes_for('pkg/test_b.py') == frozenset({'test'})
    assert config.scopes_for('pkg/b_test.py') == frozenset({'test'})
    assert config.scopes_for('conftest.py') == frozenset({'test'})
    assert config.scopes_for('pkg/module.py') == frozenset()


def test_the_table_is_found_from_a_directory_inside_the_project(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks]\nselect = ["OGC131"]\n')
    inner = tmp_path / 'sub' / 'deeper'
    inner.mkdir(parents=True)
    config = load_config(str(inner))
    assert config.root == str(tmp_path)
    assert config.selected == ('OGC131',)
    assert config.source == str(tmp_path / 'pyproject.toml')


def test_a_project_inside_another_does_not_take_the_outer_table(tmp_path):
    # The shape of a workspace of sub-projects: the outer table's paths and
    # globs are relative to the outer root and mean nothing in the inner one.
    _project(tmp_path, '[tool.openglcontext-checks]\npaths = ["tools"]\nselect = ["OGC131"]\n')
    inner = tmp_path / 'sub'
    inner.mkdir()
    _project(inner, '[project]\nname = "sub"\n')
    config = load_config(str(inner / 'pkg'))
    assert (config.root, config.source) == (str(inner), str(inner / 'pyproject.toml'))
    assert config.paths == ('.',)
    assert config.selected == tuple(sorted(EVERY_CODE))


def test_with_no_pyproject_anywhere_the_start_is_the_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, '_parents', lambda start: [start])
    config = load_config(str(tmp_path))
    assert config.root == str(tmp_path)
    assert config.source is None


def test_select_ignore_and_prefixes_decide_the_codes(tmp_path):
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks]
        select = ["OGC1", "OGC201"]
        ignore = ["OGC161"]
        """,
    )
    first_hundred = {code for code in EVERY_CODE if code.startswith('OGC1')}
    assert load_config(str(tmp_path)).selected == tuple(
        sorted(first_hundred - {'OGC161'} | {'OGC201'})
    )


def test_per_file_ignores_apply_to_the_paths_they_name(tmp_path):
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks.per-file-ignores]
        "scripts/**" = ["OGC161"]
        "conftest.py" = ["OGC2"]
        """,
    )
    config = load_config(str(tmp_path))
    assert 'OGC161' not in config.codes_for('scripts/tool.py')
    assert 'OGC161' in config.codes_for('src/tool.py')
    assert not {'OGC201', 'OGC221', 'OGC222', 'OGC223'} & config.codes_for('conftest.py')


def test_a_scope_can_be_redefined(tmp_path):
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks.scopes]
        test = ["checks/**"]
        """,
    )
    config = load_config(str(tmp_path))
    assert config.scopes_for('checks/a.py') == frozenset({'test'})
    assert config.scopes_for('tests/test_a.py') == frozenset()


def test_exclude_adds_to_the_directories_never_checked(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks]\nexclude = ["generated/**"]\n')
    config = load_config(str(tmp_path))
    assert config.is_excluded('generated/x.py')
    assert config.is_excluded('.venv/lib/x.py')
    assert config.is_excluded('pkg/__pycache__')
    assert config.is_excluded('.claude/worktrees/branch/src/x.py')
    assert config.is_excluded('docs/.samples/demo.py')
    assert not config.is_excluded('src/x.py')


def test_paths_name_what_a_run_with_no_arguments_checks(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks]\npaths = ["src", "tests"]\n')
    assert load_config(str(tmp_path)).paths == ('src', 'tests')


def test_command_line_codes_replace_select_and_add_to_ignore(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks]\nignore = ["OGC131"]\n')
    config = load_config(str(tmp_path))
    narrowed = config.with_overrides(select=['OGC131', 'OGC141', 'OGC161'], ignore=['OGC141'])
    assert narrowed.selected == ('OGC161',)
    assert config.with_overrides(select=None, ignore=['OGC2']).selected == tuple(
        sorted(code for code in EVERY_CODE if not code.startswith('OGC2') and code != 'OGC131')
    )


def test_the_settings_of_a_file_say_what_decides_its_findings(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks]\nselect = ["OGC131", "OGC222"]\n')
    config = load_config(str(tmp_path))
    assert config.settings_for('src/a.py') == 'OGC131,OGC222||'
    assert config.settings_for('tests/test_a.py') == 'OGC131,OGC222|test|'


def test_the_sanctioned_names_are_among_the_settings_of_every_file(tmp_path):
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks.sanctioned]
        OGC121 = ["game.files.staged", "game.files.replace"]
        """,
    )
    config = load_config(str(tmp_path))
    assert config.settings_for('src/a.py').endswith('|OGC121=game.files.staged,game.files.replace')


def test_a_project_names_its_own_sanctioned_api_for_a_rule(tmp_path):
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks.sanctioned]
        OGC121 = ["game.files.staged"]
        """,
    )
    assert load_config(str(tmp_path)).sanctioned == (('OGC121', ('game.files.staged',)),)
    _project(tmp_path, '[project]\nname = "x"\n')
    assert load_config(str(tmp_path)).sanctioned == ()


def test_a_rule_that_points_at_no_api_takes_no_sanctioned_names(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks.sanctioned]\nOGC131 = ["x.y"]\n')
    with pytest.raises(ConfigError, match='OGC131 points at no sanctioned API'):
        load_config(str(tmp_path))


def test_a_project_names_its_own_checked_types_for_the_mypy_plugin(tmp_path):
    _project(tmp_path, '[project]\nname = "x"\n')
    config = load_config(str(tmp_path))
    assert (config.checked_types, config.contained_paths) == ((), ())
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks]
        checked-types = ["game.tokens.Token"]
        contained-paths = ["game.files.Contained"]
        """,
    )
    config = load_config(str(tmp_path))
    assert config.checked_types == ('game.tokens.Token',)
    assert config.contained_paths == ('game.files.Contained',)


def test_the_loader_and_pass_scopes_are_empty_until_a_project_names_them(tmp_path):
    _project(tmp_path, '[project]\nname = "x"\n')
    config = load_config(str(tmp_path))
    assert config.scopes_for('pkg/loaders/gltf.py') == frozenset()
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks.scopes]
        loader = ["pkg/loaders/**"]
        pass = ["pkg/passes/**"]
        """,
    )
    config = load_config(str(tmp_path))
    assert config.scopes_for('pkg/loaders/gltf.py') == frozenset({'loader'})
    assert config.scopes_for('pkg/passes/flat.py') == frozenset({'pass'})


@pytest.mark.parametrize(
    'table, complaint',
    [
        ('selct = ["OGC131"]', "unknown key 'selct'"),
        ('select = ["OGC999"]', "select: unknown rule code 'OGC999'"),
        ('select = ["E501"]', "select: unknown rule code 'E501'"),
        ('select = "OGC131"', 'select must be a list of strings'),
        ('ignore = [131]', 'ignore must be a list of strings'),
        ('exclude = "build"', 'exclude must be a list of strings'),
        ('paths = []', 'paths must name at least one path'),
        ('per-file-ignores = ["x"]', 'per-file-ignores must be a table'),
        ('per-file-ignores = { "x.py" = ["OGC000"] }', 'per-file-ignores: unknown rule code'),
        ('scopes = { tset = ["tests/**"] }', "scopes: unknown scope 'tset'"),
        ('scopes = { test = "tests/**" }', 'scopes.test must be a list of strings'),
        ('sanctioned = ["x.y"]', 'sanctioned must be a table'),
        ('sanctioned = { OGC999 = ["x.y"] }', "sanctioned: unknown rule code 'OGC999'"),
        ('sanctioned = { OGC121 = "x.y" }', 'sanctioned.OGC121 must be a list of strings'),
        ('sanctioned = { OGC121 = [] }', 'sanctioned.OGC121 must name at least one'),
        ('sanctioned = { OGC121 = ["x y"] }', "sanctioned.OGC121: 'x y' is not a dotted name"),
        ('checked-types = "x.Y"', 'checked-types must be a list of strings'),
        ('checked-types = ["x..Y"]', "checked-types: 'x..Y' is not a dotted name"),
        ('contained-paths = ["Y"]', "contained-paths: 'Y' is not a dotted name"),
    ],
)
def test_a_bad_table_is_a_configuration_error_naming_the_fault(tmp_path, table, complaint):
    _project(tmp_path, '[tool.openglcontext-checks]\n%s\n' % (table,))
    with pytest.raises(ConfigError) as caught:
        load_config(str(tmp_path))
    assert complaint in str(caught.value)
    assert 'pyproject.toml' in str(caught.value)


def test_a_table_that_is_not_a_table_is_an_error(tmp_path):
    _project(tmp_path, '[tool]\nopenglcontext-checks = 1\n')
    with pytest.raises(ConfigError, match='must be a table'):
        load_config(str(tmp_path))


def test_a_pyproject_that_does_not_parse_is_an_error(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks\n')
    with pytest.raises(ConfigError, match='cannot read'):
        load_config(str(tmp_path))


def test_the_nearest_pyproject_is_the_root_when_none_has_the_table(tmp_path):
    _project(tmp_path, '[project]\nname = "outer"\n')
    inner = tmp_path / 'inner'
    inner.mkdir()
    _project(inner, '[project]\nname = "inner"\n')
    config = load_config(str(inner))
    assert (config.root, config.source) == (str(inner), str(inner / 'pyproject.toml'))


def test_a_named_path_lifts_the_exclusions_that_match_it(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks]\nexclude = ["generated"]\n')
    config = load_config(str(tmp_path))
    assert config.is_excluded('.claude/skills/scan.py')
    assert not config.is_excluded('.claude/skills/scan.py', '.claude/skills')
    assert config.is_excluded('.claude/skills/generated/x.py', '.claude/skills')
    assert config.is_excluded('generated/x.py', '.')


def test_the_script_scope_is_empty_until_a_project_names_its_programs(tmp_path):
    _project(tmp_path, '[project]\nname = "x"\n')
    config = load_config(str(tmp_path))
    assert config.scopes_for('scripts/tool.py') == frozenset()
    _project(tmp_path, '[tool.openglcontext-checks.scopes]\nscript = ["scripts/*.py"]\n')
    assert load_config(str(tmp_path)).scopes_for('scripts/tool.py') == frozenset({'script'})


def test_a_negated_glob_takes_paths_out_of_a_scope(tmp_path):
    _project(
        tmp_path,
        """
        [tool.openglcontext-checks.scopes]
        script = ["tests/*.py", "!tests/test_*.py", "!tests/conftest.py"]
        """,
    )
    config = load_config(str(tmp_path))
    assert config.scopes_for('tests/demo.py') == frozenset({'script', 'test'})
    assert config.scopes_for('tests/test_demo.py') == frozenset({'test'})
    assert config.scopes_for('tests/conftest.py') == frozenset({'test'})


def test_a_scope_of_only_negated_globs_holds_nothing(tmp_path):
    _project(tmp_path, '[tool.openglcontext-checks.scopes]\nscript = ["!tests/*.py"]\n')
    assert load_config(str(tmp_path)).scopes_for('scripts/tool.py') == frozenset()
