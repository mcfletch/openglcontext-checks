"""OGC121, beyond its own examples."""

import pytest

from openglcontext_checks.engine import check_source


def _found(source, **options):
    return check_source(source, codes=['OGC121'], **options)


def test_the_message_names_the_call_the_path_and_the_staging_api():
    (finding,) = _found('def save(path):\n    open(path, "w").close()\n')
    assert (finding.line, finding.column) == (2, 5)
    assert "open(..., 'w') writes path in place" in finding.message
    assert 'OpenGLContext.atomicfiles.staged_file' in finding.message


def test_a_project_names_its_own_staging_calls():
    source = (
        'from game import files\n'
        'def save(path, text):\n'
        '    with files.staged(path) as staging:\n'
        '        open(staging + "/x", "w").write(text)\n'
    )
    assert len(_found(source)) == 1
    own = {'OGC121': ('game.files.staged',)}
    assert _found(source, sanctioned=own) == []
    (finding,) = _found('def save(p):\n    open(p, "w")\n', sanctioned=own)
    assert finding.message.endswith('(game.files.staged)')


def test_a_test_writes_its_own_files():
    assert _found('def test_x(tmp_path):\n    open(tmp_path / "x", "w")\n', scopes=['test']) == []


@pytest.mark.parametrize(
    'call',
    [
        'open(path)',
        'open(path, "rb")',
        'open(path, mode)',
        'open()',
        'shutil.copyfile()',
        'tarfile.open(path)',
        'io.open(path, "r")',
    ],
)
def test_a_read_an_unknown_mode_or_a_missing_path_is_not_reported(call):
    source = 'import io, shutil, tarfile\ndef load(path, mode):\n    %s\n' % (call,)
    assert _found(source) == []


def test_the_destination_of_a_copy_given_by_keyword_is_followed():
    source = 'import shutil\ndef f(a, b):\n    shutil.copy(a, dst=b)\n'
    assert len(_found(source)) == 1


def test_another_keyword_is_not_the_destination():
    assert _found('import shutil\ndef f(a):\n    shutil.copy(a, follow_symlinks=False)\n') == []


def test_a_starred_argument_hides_the_path():
    assert _found('def f(args):\n    open(*args, "w")\n') == []


def test_a_write_under_a_temporary_directory_made_by_mkdtemp_is_not_reported():
    source = (
        'import os, tempfile\n'
        'def f(name):\n'
        '    scratch = tempfile.mkdtemp()\n'
        '    open(os.path.join(scratch, name), "w")\n'
    )
    assert _found(source) == []


def test_a_file_from_mkstemp_unpacked_is_not_reported():
    source = (
        'import tempfile\ndef f():\n    handle, where = tempfile.mkstemp()\n    open(where, "w")\n'
    )
    assert _found(source) == []


def test_every_way_to_reach_the_path_must_be_staged():
    source = (
        'import tempfile\n'
        'def f(target, scratch):\n'
        '    where = tempfile.mkdtemp() if scratch else target\n'
        '    where = target\n'
        '    open(where, "w")\n'
    )
    assert len(_found(source)) == 1


def test_a_path_written_then_renamed_by_its_own_method_is_staged():
    source = 'def f(target, partial):\n    partial.write_text("x")\n    partial.replace(target)\n'
    assert _found(source) == []


def test_a_string_path_with_a_replace_method_call_is_still_reported():
    """`str.replace` rewrites text; it moves no file."""
    source = 'def f(path):\n    open(path, "w")\n    path.replace("a", "b")\n'
    assert len(_found(source)) == 1


def test_a_rename_of_another_path_does_not_stage_this_one():
    source = 'import os\ndef f(a, b):\n    open(a, "w")\n    os.replace(b, a)\n    print()\n'
    assert len(_found(source)) == 1


def test_a_module_function_named_write_text_is_not_a_path_method():
    source = 'import atomic\ndef f(p):\n    atomic.write_text(p, "x")\n    make().write_text("x")\n'
    assert [finding.line for finding in _found(source)] == [4]


def test_a_write_at_module_level_is_reported():
    assert len(_found('open("log.txt", "w").write("x")\n')) == 1


@pytest.mark.parametrize('mode', ['a', 'ab', 'a+b', 'at'])
def test_appending_to_a_file_is_not_writing_it_in_place(mode):
    """A log, a journal or a lock file keeps what it held; there is nothing to stage."""
    assert (
        _found('import gzip\ndef f(p):\n    open(p, %r)\n    gzip.open(p, %r)\n' % (mode, mode))
        == []
    )


@pytest.mark.parametrize('mode', ['r+', 'r+b', 'w+b', 'x'])
def test_editing_or_creating_a_file_is_writing_it_in_place(mode):
    assert len(_found('def f(p):\n    open(p, %r)\n' % (mode,))) == 1


def test_appending_to_an_archive_rewrites_its_index_in_place():
    assert len(_found('import zipfile\ndef f(p):\n    zipfile.ZipFile(p, "a")\n')) == 1


@pytest.mark.parametrize(
    'call',
    [
        'pathlib.Path(where).open("w")',
        'where.open(mode="wb")',
        'self.record.open("x")',
    ],
)
def test_a_path_opened_to_write_by_its_own_method_is_reported(call):
    source = 'import pathlib\ndef save(self, where):\n    with %s as handle:\n        handle.write("x")\n' % (call,)
    assert len(_found(source)) == 1


@pytest.mark.parametrize(
    'call',
    [
        'where.open()',
        'where.open("r")',
        'where.open("a")',
        'archive.open(member, "w")',
        'archive.open("x.txt")',
        'where.open(mode)',
    ],
)
def test_a_path_opened_to_read_or_append_or_a_member_is_not_reported(call):
    source = 'def load(where, archive, member, mode):\n    return %s\n' % (call,)
    assert _found(source) == []


def test_a_path_opened_by_its_method_and_renamed_into_place_is_not_reported():
    source = (
        'import pathlib\n'
        'def save(where):\n'
        '    partial = pathlib.Path(where + ".partial")\n'
        '    with partial.open("w") as handle:\n'
        '        handle.write("x")\n'
        '    partial.replace(where)\n'
    )
    assert _found(source) == []
