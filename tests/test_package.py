"""What the distribution carries and declares."""

import pathlib
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import openglcontext_checks

PROJECT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject():
    return tomllib.loads((PROJECT / 'pyproject.toml').read_text(encoding='utf-8'))


def test_the_version_is_a_prerelease_string():
    assert openglcontext_checks.__version__ == '0.1.0a1'


def test_the_package_declares_its_types():
    package = pathlib.Path(openglcontext_checks.__file__).parent
    assert (package / 'py.typed').exists()
    assert 'py.typed' in _pyproject()['tool']['setuptools']['package-data']['openglcontext_checks']


def test_nothing_is_required_beyond_the_standard_library():
    """`tomli` stands in for `tomllib` on the one interpreter that lacks it."""
    dependencies = _pyproject()['project']['dependencies']
    assert dependencies == ['tomli>=1.1; python_version < "3.11"']


def test_the_mypy_target_is_the_supported_floor():
    data = _pyproject()
    floor = data['project']['requires-python'].lstrip('>=')
    assert data['tool']['mypy']['python_version'] == floor
