"""`-p openglcontext_checks.pytest_plugin`: the rules as items of a project's suite."""

import importlib.metadata
import textwrap

import pytest

from openglcontext_checks import pytest_plugin as plugin

PLUGIN = ('-p', 'openglcontext_checks.pytest_plugin')
KEYED = 'cache = {}\ndef fit(mesh):\n    cache[id(mesh)] = 1\n'
PASSING = 'def test_passes():\n    assert True\n'


@pytest.fixture
def project(pytester):
    def make(files, table='[tool.openglcontext-checks]\nselect = ["OGC131", "OGC222"]\n'):
        pytester.makefile('.toml', pyproject='[project]\nname = "p"\n' + table)
        for name, text in files.items():
            path = pytester.path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text), encoding='utf-8')
        return pytester

    return make


def test_the_suite_gains_one_item_per_selected_rule(project):
    pytester = project({'pkg/fit.py': KEYED, 'tests/test_ok.py': PASSING})
    result = pytester.runpytest(*PLUGIN, '-v')
    result.assert_outcomes(passed=2, failed=1)
    result.stdout.fnmatch_lines(
        [
            '*oglc-check?OGC131? FAILED*',
            '*oglc-check?OGC222? PASSED*',
        ]
    )


def test_a_failing_rule_lists_its_findings(project):
    pytester = project({'pkg/fit.py': KEYED, 'tests/test_ok.py': PASSING})
    result = pytester.runpytest(*PLUGIN)
    result.assert_outcomes(passed=2, failed=1)
    result.stdout.fnmatch_lines(['*pkg/fit.py:3:11: OGC131 id(mesh) as a key*'])


def test_a_clean_project_passes_every_rule_item(project):
    pytester = project({'pkg/fine.py': 'x = 1\n', 'tests/test_ok.py': PASSING})
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=3)


def test_a_run_naming_its_own_paths_is_left_alone(project):
    """A developer running one file wants that file's tests, not the project's rules."""
    pytester = project({'pkg/fit.py': KEYED, 'tests/test_ok.py': PASSING})
    pytester.runpytest(*PLUGIN, 'tests/test_ok.py').assert_outcomes(passed=1)
    forced = pytester.runpytest(*PLUGIN, '--oglc-check', 'tests/test_ok.py')
    forced.assert_outcomes(passed=2, failed=1)


def test_an_item_can_be_deselected_like_any_other(project):
    pytester = project({'pkg/fit.py': KEYED, 'tests/test_ok.py': PASSING})
    result = pytester.runpytest(*PLUGIN, '-k', 'not OGC131')
    result.assert_outcomes(passed=2, deselected=1)


def test_a_file_that_does_not_parse_fails_every_rule_item(project):
    pytester = project({'pkg/broken.py': 'def broken(:\n', 'tests/test_ok.py': PASSING})
    result = pytester.runpytest(*PLUGIN)
    result.assert_outcomes(passed=1, failed=2)
    result.stdout.fnmatch_lines(['*pkg/broken.py:1:*cannot parse*'])


def test_a_bad_configuration_stops_the_session(project):
    pytester = project({'tests/test_ok.py': PASSING}, table='[tool.openglcontext-checks]\nx = 1\n')
    result = pytester.runpytest(*PLUGIN)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*unknown key 'x'*"])


def test_the_items_report_where_they_come_from(project):
    pytester = project({'tests/test_ok.py': PASSING})
    recorder = pytester.inline_run(*PLUGIN, '--collect-only')
    (finished,) = recorder.getcalls('pytest_collection_finish')
    rules = [item for item in finished.session.items if item.name.startswith('oglc-check')]
    assert [item.name for item in rules] == ['oglc-check[OGC131]', 'oglc-check[OGC222]']
    path, line, description = rules[0].reportinfo()
    assert (line, description) == (None, 'oglc-check OGC131')
    assert str(path) == str(pytester.path)


def test_another_failure_inside_an_item_is_reported_as_pytest_would(project, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError('the runner broke')

    monkeypatch.setattr(plugin, 'check_files', broken)
    pytester = project({'tests/test_ok.py': PASSING})
    result = pytester.runpytest(*PLUGIN)
    result.assert_outcomes(passed=1, failed=2)
    result.stdout.fnmatch_lines(['*RuntimeError: the runner broke*'])


def test_installing_the_package_changes_no_one_s_suite():
    """No `pytest11` entry point: a project opts in with `-p`."""
    plugins = importlib.metadata.entry_points(group='pytest11')
    assert not [entry for entry in plugins if 'openglcontext_checks' in entry.value]
