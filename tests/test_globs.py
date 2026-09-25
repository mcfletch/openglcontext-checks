"""Matching a project-relative path against a configured glob."""

import pytest

from openglcontext_checks.globs import matches


@pytest.mark.parametrize(
    'pattern, path, expected',
    [
        # No slash: any one component, file or directory.
        ('build', 'build/lib/x.py', True),
        ('build', 'src/build/x.py', True),
        ('build', 'src/builder.py', False),
        ('*.egg-info', 'src/pkg.egg-info/PKG-INFO', True),
        ('test_*.py', 'deep/in/test_thing.py', True),
        ('conftest.py', 'conftest.py', True),
        # A slash: anchored at the project root, and a directory covers what is under it.
        ('tests/**', 'tests/unit/test_a.py', True),
        ('tests/**', 'src/tests/test_a.py', False),
        ('docs/_build', 'docs/_build/html/x.py', True),
        ('./docs/_build/', 'docs/_build/x.py', True),
        ('src/*.py', 'src/a.py', True),
        ('src/*.py', 'src/pkg/a.py', False),
        ('**/test_*.py', 'test_top.py', True),
        ('**/test_*.py', 'a/b/test_deep.py', True),
        ('**/test_*.py', 'a/b/check_deep.py', False),
        ('a/**/z.py', 'a/z.py', True),
        ('a/**/z.py', 'a/b/c/z.py', True),
        ('src/?.py', 'src/a.py', True),
        ('src/?.py', 'src/ab.py', False),
        ('src/[ab].py', 'src/b.py', True),
        ('src/[!ab].py', 'src/b.py', False),
        ('src/[!ab].py', 'src/c.py', True),
        ('src/a+b.py', 'src/a+b.py', True),
        ('src/[unclosed.py', 'src/[unclosed.py', True),
    ],
)
def test_a_glob_matches_as_documented(pattern, path, expected):
    assert matches(pattern, path) is expected
