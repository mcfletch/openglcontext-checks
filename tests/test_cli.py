"""`oglc-check`: what it checks, what it prints and how it exits."""

import os
import textwrap

import pytest

from openglcontext_checks import __version__, cli, runner
from openglcontext_checks.cache import CACHE_DIRECTORY

KEYED = 'cache = {}\ndef fit(mesh):\n    cache[id(mesh)] = 1\n'
UNASSERTED = 'def test_draws():\n    draw()\n'


def _write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding='utf-8')


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project directory with a pyproject.toml, and the working directory in it."""

    def make(files, table=''):
        _write(tmp_path, {'pyproject.toml': '[project]\nname = "p"\n' + table, **files})
        monkeypatch.chdir(tmp_path)
        return tmp_path

    return make


def _run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out.splitlines(), captured.err


def test_a_clean_project_exits_zero_and_prints_nothing(project, capsys):
    project({'pkg/mod.py': 'x = 1\n'})
    assert _run(capsys) == (0, [], '')


def test_findings_are_printed_sorted_and_exit_one(project, capsys):
    project({'b.py': KEYED, 'a.py': KEYED, 'tests/test_x.py': UNASSERTED})
    code, lines, _err = _run(capsys)
    assert code == 1
    assert [line.split(': ')[0] for line in lines] == [
        'a.py:3:11',
        'b.py:3:11',
        'tests/test_x.py:1:1',
    ]
    assert lines[0].startswith('a.py:3:11: OGC131 id(mesh) as a key')
    assert 'OGC222 test_draws has no assertion' in lines[2]


def test_a_test_rule_is_confined_to_the_test_scope(project, capsys):
    project({'src/draw.py': UNASSERTED})
    assert _run(capsys)[0] == 0


def test_statistics_count_findings_per_code(project, capsys):
    project({'a.py': KEYED, 'b.py': KEYED, 'tests/test_x.py': UNASSERTED})
    code, lines, _err = _run(capsys, '--statistics')
    assert code == 1
    assert lines == ['    2  OGC131  id() as a key', '    1  OGC222  test with no assertion']


def test_select_and_ignore_on_the_command_line(project, capsys):
    project({'a.py': KEYED, 'tests/test_x.py': UNASSERTED})
    assert [line.split()[1] for line in _run(capsys, '--select', 'OGC222')[1]] == ['OGC222']
    assert [line.split()[1] for line in _run(capsys, '--ignore', 'OGC1')[1]] == ['OGC222']
    assert _run(capsys, '--select', 'OGC131,OGC222', '--ignore', 'OGC131,OGC222')[0] == 0


def test_an_unknown_code_on_the_command_line_is_a_usage_error(project, capsys):
    project({'a.py': 'x = 1\n'})
    code, _lines, err = _run(capsys, '--select', 'OGC999')
    assert code == 2
    assert "unknown rule code 'OGC999'" in err


def test_a_bad_configuration_exits_two(project, capsys):
    project({'a.py': 'x = 1\n'}, table='[tool.openglcontext-checks]\nselct = []\n')
    code, _lines, err = _run(capsys)
    assert code == 2
    assert "unknown key 'selct'" in err


def test_an_unparsable_file_is_named_and_exits_two(project, capsys):
    project({'a.py': KEYED, 'broken.py': 'def broken(:\n'})
    code, lines, err = _run(capsys)
    assert code == 2
    assert 'broken.py:1:' in err and 'cannot parse' in err
    assert len(lines) == 1


def test_a_path_that_is_not_there_exits_two(project, capsys):
    project({'a.py': 'x = 1\n'})
    code, _lines, err = _run(capsys, 'missing.py')
    assert code == 2
    assert 'missing.py' in err


def test_named_paths_are_checked_instead_of_the_configured_ones(project, capsys):
    project({'a.py': KEYED, 'sub/b.py': KEYED, 'sub/notes.txt': 'not python'})
    assert [line.split(':')[0] for line in _run(capsys, 'sub')[1]] == ['sub/b.py']
    assert [line.split(':')[0] for line in _run(capsys, 'a.py')[1]] == ['a.py']


def test_configured_paths_and_exclusions_decide_an_unnamed_run(project, capsys):
    table = '[tool.openglcontext-checks]\npaths = ["src"]\nexclude = ["src/generated"]\n'
    project(
        {'src/a.py': KEYED, 'src/generated/b.py': KEYED, 'other/c.py': KEYED, 'build/d.py': KEYED},
        table=table,
    )
    assert [line.split(':')[0] for line in _run(capsys)[1]] == ['src/a.py']


def test_a_named_path_is_checked_whatever_the_exclusions_say(project, capsys):
    """As ruff does: naming a path is asking for it."""
    project({'build/d.py': KEYED, 'build/sub/.cache/e.py': KEYED})
    assert _run(capsys)[0] == 0
    assert [line.split(':')[0] for line in _run(capsys, 'build/d.py')[1]] == [
        os.path.join('build', 'd.py')
    ]
    assert [line.split(':')[0] for line in _run(capsys, 'build')[1]] == [
        os.path.join('build', 'd.py')
    ]


def test_a_run_from_a_subdirectory_prints_paths_from_there(project, capsys, monkeypatch):
    root = project({'a.py': KEYED, 'sub/b.py': KEYED})
    monkeypatch.chdir(root / 'sub')
    assert [line.split(':')[0] for line in _run(capsys)[1]] == [
        os.path.join('..', 'a.py'),
        'b.py',
    ]


def test_a_reasoned_noqa_suppresses_and_an_unreasoned_one_is_reported(project, capsys):
    project(
        {
            'a.py': 'cache[id(m)] = 1  # noqa: OGC131 m lives as long as the cache\n',
            'b.py': 'cache[id(m)] = 1  # noqa: OGC131\n',
        }
    )
    codes = [(line.split(':')[0], line.split()[1]) for line in _run(capsys)[1]]
    assert codes == [('b.py', 'OGC131'), ('b.py', 'OGC201')]


def test_a_second_run_reports_the_same_from_its_cache(project, capsys):
    root = project({'a.py': KEYED, 'tests/test_x.py': UNASSERTED})
    first = _run(capsys)
    assert (root / CACHE_DIRECTORY / 'results.json').exists()
    assert _run(capsys) == first


def test_no_cache_writes_no_cache(project, capsys):
    root = project({'a.py': KEYED})
    assert _run(capsys, '--no-cache')[0] == 1
    assert not (root / CACHE_DIRECTORY).exists()


def test_many_files_are_checked_in_parallel_with_the_same_result(project, capsys, monkeypatch):
    files = {'pkg/m%02d.py' % index: KEYED for index in range(12)}
    files['broken.py'] = 'def broken(:\n'
    project(files)
    serial = _run(capsys, '--no-cache', '--jobs', '1')
    monkeypatch.setattr(runner, 'PARALLEL_THRESHOLD', 4)
    parallel = _run(capsys, '--no-cache', '--jobs', '2')
    assert parallel == serial
    assert len(serial[1]) == 12


def test_version(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(['--version'])
    assert caught.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_an_unknown_option_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(['--frobnicate'])
    assert caught.value.code == 2
    assert 'usage' in capsys.readouterr().err


def test_a_dot_directory_is_skipped_unless_it_is_named(project, capsys):
    """Tool state, virtualenvs and worktrees live in them."""
    project({'.claude/worktrees/b/a.py': KEYED, '.hidden/tool.py': KEYED})
    assert _run(capsys)[0] == 0
    assert [line.split(':')[0] for line in _run(capsys, '.hidden')[1]] == [
        os.path.join('.hidden', 'tool.py')
    ]
