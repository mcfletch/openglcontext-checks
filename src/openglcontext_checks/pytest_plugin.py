"""The OGC rules as items of a project's pytest suite.

Opt in from the project's pytest configuration:

    [tool.pytest.ini_options]
    addopts = "-p openglcontext_checks.pytest_plugin"

The package declares no `pytest11` entry point, so installing it changes no
suite that does not ask for it.

A run of the suite (pytest started with no paths, collecting its `testpaths`
or the current directory) then includes one item per selected rule,
`oglc-check[OGC131]` and so on. The rules run once, over the project's
configured paths with its `[tool.openglcontext-checks]` settings and result
cache, and each item fails with its rule's findings listed. A run naming paths
of its own is left alone unless `--oglc-check` is given. A file that cannot be
parsed fails every item, since no rule has checked it; a configuration error
stops the session as a usage error.
"""

from __future__ import annotations

from typing import Any

import pytest

from .config import ConfigError, load_config
from .runner import Report, check_files, discover


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup('oglc-check')
    group.addoption(
        '--oglc-check',
        action='store_true',
        dest='oglc_check',
        help='include the OGC rule items even when the run names its own paths',
    )


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    # First, so that -k and -m deselect these items like any others.
    if not _wanted(config):
        return
    root = str(config.rootpath)
    try:
        settings = load_config(root)
        files = discover(settings, None, root)
    except ConfigError as error:
        raise pytest.UsageError('oglc-check: %s' % (error,)) from None
    run = _Run(lambda: check_files(settings, files, cwd=root))
    for code in settings.selected:
        items.append(
            RuleItem.from_parent(session, name='oglc-check[%s]' % (code,), code=code, run=run)
        )


def _wanted(config: pytest.Config) -> bool:
    """Whether this session is a run of the suite, or asked for the items."""
    if config.getoption('oglc_check'):
        return True
    return bool(config.args_source != pytest.Config.ArgsSource.ARGS)


class _Run:
    """The rules' one run for the session, made when the first item needs it."""

    def __init__(self, check: Any) -> None:
        self._check = check
        self._report: Report | None = None

    def report(self) -> Report:
        if self._report is None:
            self._report = self._check()
        assert self._report is not None
        return self._report


class RuleFailure(Exception):
    """A rule's findings, or the files no rule could check."""


class RuleItem(pytest.Item):
    """One rule, run over the project."""

    def __init__(self, *, code: str, run: _Run, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.code = code
        self._run = run

    def runtest(self) -> None:
        report = self._run.report()
        lines = [
            finding.format(path) for path, finding in report.findings if finding.code == self.code
        ]
        lines.extend(report.errors)
        if lines:
            raise RuleFailure('\n'.join(lines))

    def repr_failure(self, excinfo: pytest.ExceptionInfo[BaseException], style: Any = None) -> Any:
        if isinstance(excinfo.value, RuleFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo, style=style)

    def reportinfo(self) -> tuple[Any, int | None, str]:
        return self.path, None, 'oglc-check %s' % (self.code,)
