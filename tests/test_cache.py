"""The per-project result cache."""

import json
import os
import shutil

import pytest

import openglcontext_checks
from openglcontext_checks import cache as cache_module
from openglcontext_checks.cache import (
    CACHE_DIRECTORY,
    ResultCache,
    entry_key,
    implementation_digest,
)
from openglcontext_checks.findings import Finding

FOUND = [Finding(3, 1, 'OGC131', 'id(x) as a key')]


@pytest.fixture(autouse=True)
def sources(tmp_path):
    """The files the cached entries are for: an entry for a file that is gone is dropped."""
    for name in ('a.py', 'b.py'):
        (tmp_path / name).write_text('x = 1\n')


def test_a_stored_result_comes_back_for_the_same_key(tmp_path):
    cache = ResultCache(str(tmp_path))
    key = entry_key(b'x = 1\n', 'OGC131|')
    cache.store('a.py', key, FOUND)
    cache.save()
    again = ResultCache(str(tmp_path))
    assert again.lookup('a.py', key) == FOUND
    assert again.lookup('a.py', entry_key(b'x = 2\n', 'OGC131|')) is None
    assert again.lookup('b.py', key) is None


def test_the_key_covers_content_settings_and_the_rules_themselves(monkeypatch):
    base = entry_key(b'x = 1\n', 'OGC131|')
    assert entry_key(b'x = 1\n', 'OGC131|') == base
    assert entry_key(b'x = 2\n', 'OGC131|') != base
    assert entry_key(b'x = 1\n', 'OGC131,OGC141|') != base
    # A rule edited in an editable install changes the findings without a new
    # version number; the key follows the package's source, not its version.
    monkeypatch.setattr(cache_module, 'implementation', lambda: 'edited rules')
    assert entry_key(b'x = 1\n', 'OGC131|') != base


def test_the_digest_follows_every_source_file_of_the_package(tmp_path):
    package = os.path.dirname(openglcontext_checks.__file__)
    copy = tmp_path / 'copy'
    shutil.copytree(package, copy, ignore=shutil.ignore_patterns('__pycache__'))
    before = implementation_digest(str(copy))
    assert implementation_digest(str(copy)) == before
    rule = copy / 'rules' / 'ogc131_id_key.py'
    rule.write_text(rule.read_text() + '\n# edited\n')
    edited = implementation_digest(str(copy))
    assert edited != before
    (copy / '__pycache__').mkdir()
    (copy / '__pycache__' / 'stale.pyc').write_bytes(b'not source')
    (copy / 'notes.txt').write_text('not source')
    assert implementation_digest(str(copy)) == edited


def test_a_cache_written_by_other_rules_is_not_read(tmp_path):
    cache = ResultCache(str(tmp_path))
    key = entry_key(b'x', 's')
    cache.store('a.py', key, FOUND)
    cache.save()
    path = tmp_path / CACHE_DIRECTORY / 'results.json'
    data = json.loads(path.read_text())
    assert data['version'] == cache_module.implementation()
    data['version'] = '0.0.0'
    path.write_text(json.dumps(data))
    assert ResultCache(str(tmp_path)).lookup('a.py', key) is None


def test_an_unreadable_cache_starts_empty(tmp_path):
    (tmp_path / CACHE_DIRECTORY).mkdir()
    (tmp_path / CACHE_DIRECTORY / 'results.json').write_text('{not json')
    assert ResultCache(str(tmp_path)).lookup('a.py', 'k') is None
    (tmp_path / CACHE_DIRECTORY / 'results.json').write_text('[1, 2]')
    assert ResultCache(str(tmp_path)).lookup('a.py', 'k') is None


def test_the_cache_directory_ignores_itself(tmp_path):
    cache = ResultCache(str(tmp_path))
    cache.store('a.py', 'k', [])
    cache.save()
    assert (tmp_path / CACHE_DIRECTORY / '.gitignore').read_text() == '*\n'


def test_nothing_is_written_when_nothing_changed(tmp_path):
    cache = ResultCache(str(tmp_path))
    cache.save()
    assert not (tmp_path / CACHE_DIRECTORY).exists()
    cache.store('a.py', 'k', [])
    cache.save()
    path = tmp_path / CACHE_DIRECTORY / 'results.json'
    before = path.stat().st_mtime_ns
    os.utime(path, ns=(before - 10**9, before - 10**9))
    reread = ResultCache(str(tmp_path))
    assert reread.lookup('a.py', 'k') == []
    reread.store('a.py', 'k', [])
    reread.save()
    assert path.stat().st_mtime_ns == before - 10**9


def test_entries_for_files_that_are_gone_are_dropped(tmp_path):
    cache = ResultCache(str(tmp_path))
    cache.store('a.py', 'k', [])
    cache.store('gone.py', 'k', [])
    cache.save()
    data = json.loads((tmp_path / CACHE_DIRECTORY / 'results.json').read_text())
    assert sorted(data['files']) == ['a.py']


def test_the_write_replaces_the_file_whole(tmp_path, monkeypatch):
    """A temporary file beside it, then one rename."""
    replaced = []
    real_replace = os.replace

    def record(source, target):
        replaced.append((os.path.dirname(source), os.path.basename(target)))
        real_replace(source, target)

    monkeypatch.setattr(os, 'replace', record)
    cache = ResultCache(str(tmp_path))
    cache.store('a.py', 'k', FOUND)
    cache.save()
    directory = str(tmp_path / CACHE_DIRECTORY)
    assert (directory, 'results.json') in replaced
    assert sorted(os.listdir(directory)) == ['.gitignore', 'results.json']


def test_a_cache_that_cannot_be_written_is_reported_and_not_fatal(tmp_path, capsys):
    blocker = tmp_path / CACHE_DIRECTORY
    blocker.write_text('a file where the directory goes')
    cache = ResultCache(str(tmp_path))
    cache.store('a.py', 'k', [])
    cache.save()
    assert 'could not write the result cache' in capsys.readouterr().err


def test_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    def refuse(_source, target):
        raise PermissionError(target)

    monkeypatch.setattr(os, 'replace', refuse)
    cache = ResultCache(str(tmp_path))
    cache.store('a.py', 'k', [])
    cache.save()
    assert os.listdir(tmp_path / CACHE_DIRECTORY) == []


def test_a_disabled_cache_neither_reads_nor_writes(tmp_path):
    cache = ResultCache(str(tmp_path))
    cache.store('a.py', 'k', FOUND)
    cache.save()
    disabled = ResultCache(str(tmp_path), enabled=False)
    assert disabled.lookup('a.py', 'k') is None
    disabled.store('b.py', 'k', FOUND)
    disabled.save()
    data = json.loads((tmp_path / CACHE_DIRECTORY / 'results.json').read_text())
    assert sorted(data['files']) == ['a.py']


def test_an_entry_of_the_wrong_shape_is_a_miss(tmp_path):
    (tmp_path / CACHE_DIRECTORY).mkdir()
    (tmp_path / CACHE_DIRECTORY / 'results.json').write_text(
        json.dumps(
            {
                'version': cache_module.implementation(),
                'files': {'a.py': {'key': 'k', 'findings': 7}},
            }
        )
    )
    assert ResultCache(str(tmp_path)).lookup('a.py', 'k') is None


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_the_cache_files_take_the_umask_like_any_other_file(tmp_path):
    previous = os.umask(0o022)
    try:
        cache = ResultCache(str(tmp_path))
        cache.store('a.py', 'k', [])
        cache.save()
    finally:
        os.umask(previous)
    for name in ('.gitignore', 'results.json'):
        assert (tmp_path / CACHE_DIRECTORY / name).stat().st_mode & 0o777 == 0o644
