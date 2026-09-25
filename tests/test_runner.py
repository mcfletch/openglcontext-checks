"""Discovering files and checking them, with the cache between runs."""

import os
import pickle

import pytest

from openglcontext_checks import runner
from openglcontext_checks.config import ConfigError, load_config
from openglcontext_checks.engine import ParseError
from openglcontext_checks.runner import check_files, discover

KEYED = 'cache = {}\ndef fit(mesh):\n    cache[id(mesh)] = 1\n'


@pytest.fixture
def root(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "p"\n')
    (tmp_path / 'a.py').write_text(KEYED)
    (tmp_path / 'b.py').write_text('x = 1\n')
    return tmp_path


def _check(root, config=None, **options):
    config = config or load_config(str(root))
    return check_files(config, discover(config, None, str(root)), cwd=str(root), **options)


def test_a_second_run_parses_nothing_and_reports_the_same(root):
    first = _check(root)
    second = _check(root)
    assert (first.files, first.parsed) == (2, 2)
    assert (second.files, second.parsed) == (2, 0)
    assert second.findings == first.findings
    assert [path for path, _finding in second.findings] == ['a.py']


def test_an_edited_file_is_parsed_again(root):
    _check(root)
    (root / 'b.py').write_text(KEYED)
    report = _check(root)
    assert report.parsed == 1
    assert [path for path, _finding in report.findings] == ['a.py', 'b.py']


def test_a_changed_configuration_parses_again(root):
    _check(root)
    narrowed = load_config(str(root)).with_overrides(select=['OGC201'], ignore=[])
    report = _check(root, narrowed)
    assert (report.parsed, report.findings) == (2, [])


def test_without_the_cache_every_file_is_parsed(root):
    _check(root)
    assert _check(root, cache=False).parsed == 2


def test_an_unreadable_file_is_an_error_not_a_crash(root):
    (root / 'c.py').mkdir()
    config = load_config(str(root))
    report = check_files(config, [str(root / 'c.py')], cwd=str(root))
    assert report.errors and 'c.py' in report.errors[0]


def test_discovery_refuses_a_missing_path(root):
    with pytest.raises(ConfigError, match='no such file or directory'):
        discover(load_config(str(root)), ['nowhere'], str(root))


def test_discovery_lists_python_files_once_in_order(root):
    config = load_config(str(root))
    files = discover(config, ['.', 'a.py'], str(root))
    assert files == [str(root / 'a.py'), str(root / 'b.py')]


def test_a_file_on_another_drive_is_shown_by_its_full_path(root, monkeypatch):
    """`os.path.relpath` refuses across Windows drives."""
    elsewhere = root / 'elsewhere'
    elsewhere.mkdir()
    relpath = os.path.relpath

    def across_drives(path, start=os.curdir):
        if start == str(elsewhere):
            raise ValueError('path is on mount %r, start on mount %r' % (path, start))
        return relpath(path, start)

    config = load_config(str(root))
    files = discover(config, ['a.py'], str(root))
    monkeypatch.setattr(runner.os.path, 'relpath', across_drives)
    report = check_files(config, files, cwd=str(elsewhere), cache=False)
    assert [shown for shown, _finding in report.findings] == files


def test_a_parse_error_survives_the_trip_from_a_worker():
    pickled = pickle.dumps(ParseError('x.py', 3, 4, 'invalid syntax'))
    error = pickle.loads(pickled)  # noqa: S301 bytes this test pickled itself
    assert (error.path, error.line, error.column, error.message) == ('x.py', 3, 4, 'invalid syntax')


@pytest.fixture
def configured(tmp_path):
    """A project that names its paths and excludes a directory inside them."""
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "p"\n[tool.openglcontext-checks]\n'
        'paths = ["src"]\nexclude = ["src/generated"]\n'
    )
    for name in ('src/pkg/a.py', 'src/generated/b.py', 'docs/conf.py'):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text('x = 1\n')
    return tmp_path


def test_a_named_file_is_checked_whatever_the_configuration_says(configured):
    config = load_config(str(configured))
    named = ['src/pkg/a.py', 'src/generated/b.py', 'docs/conf.py']
    assert discover(config, named, str(configured)) == sorted(
        str(configured / name) for name in named
    )


def test_force_exclude_keeps_a_named_file_the_configuration_would_check(configured):
    config = load_config(str(configured))
    files = discover(config, ['src/pkg/a.py'], str(configured), force_exclude=True)
    assert files == [str(configured / 'src/pkg/a.py')]


@pytest.mark.parametrize('name', ['src/generated/b.py', 'src/generated', 'docs/conf.py', 'docs'])
def test_force_exclude_drops_a_named_path_the_configuration_leaves_out(configured, name):
    config = load_config(str(configured))
    assert discover(config, [name], str(configured), force_exclude=True) == []


def test_force_exclude_drops_a_path_outside_the_project(configured, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp('elsewhere') / 'c.py'
    elsewhere.write_text('x = 1\n')
    config = load_config(str(configured))
    assert discover(config, [str(elsewhere)], str(configured), force_exclude=True) == []


def test_force_exclude_walks_a_named_directory_with_every_exclusion(configured):
    config = load_config(str(configured))
    files = discover(config, ['src'], str(configured), force_exclude=True)
    assert files == [str(configured / 'src/pkg/a.py')]


def test_force_exclude_keeps_everything_where_the_paths_are_the_whole_project(root):
    config = load_config(str(root))
    assert discover(config, ['a.py'], str(root), force_exclude=True) == [str(root / 'a.py')]


def test_force_exclude_still_refuses_a_missing_path(configured):
    with pytest.raises(ConfigError, match='no such file or directory'):
        discover(
            load_config(str(configured)), ['docs/gone.py'], str(configured), force_exclude=True
        )
