"""Discovering files and checking them, with the cache between runs."""

import pytest

from openglcontext_checks.config import ConfigError, load_config
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
    import openglcontext_checks.runner as runner

    def across_drives(path, start):
        raise ValueError('path is on mount %r, start on mount %r' % (path, start))

    config = load_config(str(root))
    files = discover(config, None, str(root))
    monkeypatch.setattr(runner.os.path, 'relpath', across_drives)
    assert runner._shown(files[0], str(root)) == files[0]


def test_a_parse_error_survives_the_trip_from_a_worker():
    import pickle

    from openglcontext_checks.engine import ParseError

    error = pickle.loads(pickle.dumps(ParseError('x.py', 3, 4, 'invalid syntax')))
    assert (error.path, error.line, error.column, error.message) == ('x.py', 3, 4, 'invalid syntax')
