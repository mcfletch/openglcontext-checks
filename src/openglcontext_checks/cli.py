"""`oglc-check`: run the OGC rules over a project.

    oglc-check                        # the project's configured paths
    oglc-check src/pkg/module.py      # just these files or directories
    oglc-check --statistics           # how many findings of each rule
    oglc-check --select OGC131,OGC2   # these rules only
    oglc-check --ignore OGC222        # all but these

Findings print as `path:line:column: CODE message`, in path and line order.
The exit status is 0 when there are none, 1 when there are, and 2 when the
command line or the configuration is wrong or a file could not be parsed.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, load_config
from .rules import RULES
from .runner import check_files, discover


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command with `argv` (default the process's); the exit status."""
    parser = argparse.ArgumentParser(
        prog='oglc-check',
        description='Run the OGC rules over Python files.',
        epilog='Exit status: 0 clean, 1 findings, 2 a usage, configuration or parse error.',
    )
    parser.add_argument(
        'paths', nargs='*', help="files or directories; default the project's configured paths"
    )
    parser.add_argument(
        '--select',
        metavar='CODES',
        help='comma-separated codes or prefixes to run, replacing the configured selection',
    )
    parser.add_argument(
        '--ignore', metavar='CODES', help='comma-separated codes or prefixes not to run'
    )
    parser.add_argument(
        '--statistics', action='store_true', help='print the number of findings of each rule'
    )
    parser.add_argument('--no-cache', action='store_true', help='neither read nor write the cache')
    parser.add_argument(
        '--jobs',
        type=int,
        metavar='N',
        help='worker processes for a large run (default: CPUs, up to 8)',
    )
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)
    options = parser.parse_args(argv)

    cwd = os.getcwd()
    try:
        config = load_config(cwd).with_overrides(
            select=_codes(options.select) if options.select is not None else None,
            ignore=_codes(options.ignore) if options.ignore is not None else [],
        )
        files = discover(config, options.paths or None, cwd)
    except ConfigError as error:
        print('oglc-check: %s' % (error,), file=sys.stderr)
        return 2

    report = check_files(config, files, cwd=cwd, cache=not options.no_cache, jobs=options.jobs)
    for problem in report.errors:
        print(problem, file=sys.stderr)
    try:
        if options.statistics:
            counts = collections.Counter(finding.code for _path, finding in report.findings)
            for code, count in sorted(counts.items()):
                print('%5d  %s  %s' % (count, code, RULES[code].name))
        else:
            for path, finding in report.findings:
                print(finding.format(path))
    except BrokenPipeError:
        # The reader stopped reading (`oglc-check | head`). Standard output is
        # pointed at the null device, so the flush at exit does not raise too.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    if report.errors:
        return 2
    return 1 if report.findings else 0


def _codes(text: str) -> list[str]:
    return [code.strip() for code in text.split(',') if code.strip()]


if __name__ == '__main__':  # pragma: no cover - `python -m openglcontext_checks.cli`
    sys.exit(main())
