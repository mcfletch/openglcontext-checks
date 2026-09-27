"""What the distribution carries and declares."""

import pathlib
import shutil
import subprocess
import sys
import tarfile

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


def test_the_sdist_carries_the_whole_suite(tmp_path):
    """The suite is run from the unpacked sdist, so a helper it leaves out
    (``conftest.py`` enabling ``pytester``) fails there and nowhere else.

    Built from a copy so the build writes nothing into the checkout.
    """
    source = tmp_path / 'project'
    shutil.copytree(PROJECT, source, ignore=shutil.ignore_patterns(
        '.*', '__pycache__', '*.egg-info', 'build', 'dist'))
    subprocess.run(
        [sys.executable, '-c',
         'import sys; from setuptools import build_meta; '
         'print(build_meta.build_sdist(sys.argv[1]))',
         str(tmp_path / 'dist')],
        cwd=source, check=True, capture_output=True, text=True)
    [archive] = (tmp_path / 'dist').glob('*.tar.gz')
    with tarfile.open(archive) as sdist:
        carried = {pathlib.PurePosixPath(*pathlib.PurePosixPath(name).parts[1:])
                   for name in sdist.getnames()}
    suite = {pathlib.PurePosixPath(path.relative_to(source).as_posix())
             for path in (source / 'tests').rglob('*') if path.is_file()}
    assert sorted(map(str, suite - carried)) == []


def test_the_mypy_target_is_the_supported_floor():
    data = _pyproject()
    floor = data['project']['requires-python'].lstrip('>=')
    assert data['tool']['mypy']['python_version'] == floor
