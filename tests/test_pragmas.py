"""Reading `# noqa` and `# type: ignore` out of a module's comments."""

import pytest

from openglcontext_checks.pragmas import NOQA, TYPE_IGNORE, Pragma, read_pragmas


def _only(source):
    found = read_pragmas(source.encode('utf-8'))
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize(
    'comment, codes, reason',
    [
        ('# noqa: OGC131 the cache holds the object', ('OGC131',), 'the cache holds the object'),
        ('# noqa: E501, OGC131 shared with ruff', ('E501', 'OGC131'), 'shared with ruff'),
        ('# noqa: E501 OGC131 - both', ('E501', 'OGC131'), 'both'),
        ('# noqa:E501,W291 -- tidy later', ('E501', 'W291'), 'tidy later'),
        ('# NOQA: E501 upper case', ('E501',), 'upper case'),
        ('# noqa: E501', ('E501',), ''),
        ('# noqa: E501 --', ('E501',), ''),
        ('# noqa: E501 — a dash', ('E501',), 'a dash'),
        ('# noqa', (), ''),
        ('# noqa the reason', (), 'the reason'),
        ('# noqa:', (), ''),
    ],
)
def test_a_noqa_comment_names_its_codes_and_its_reason(comment, codes, reason):
    pragma = _only('x = 1  %s\n' % (comment,))
    assert pragma.kind == NOQA
    assert pragma.codes == codes
    assert pragma.reason == reason


@pytest.mark.parametrize(
    'comment, codes, reason',
    [
        (
            '# type: ignore[attr-defined] numpy stubs lack it',
            ('attr-defined',),
            'numpy stubs lack it',
        ),
        ('# type: ignore[a, b]: two', ('a', 'b'), 'two'),
        ('# type: ignore[attr-defined]', ('attr-defined',), ''),
        ('# type: ignore', (), ''),
        ('# type: ignore[]', (), ''),
        ('# type:ignore[x] tight spacing', ('x',), 'tight spacing'),
    ],
)
def test_a_type_ignore_names_its_codes_and_its_reason(comment, codes, reason):
    pragma = _only('x = 1  %s\n' % (comment,))
    assert pragma.kind == TYPE_IGNORE
    assert pragma.codes == codes
    assert pragma.reason == reason


def test_a_reason_may_follow_in_a_comment_of_its_own():
    """`# type: ignore[x]  # why` is the form mypy's documentation shows."""
    pragma = _only('x = 1  # type: ignore[attr-defined]  # the stubs lack it\n')
    assert pragma.reason == 'the stubs lack it'


def test_a_following_pragma_is_not_a_reason():
    found = read_pragmas(b'x = 1  # type: ignore[x]  # noqa: E501\n')
    assert [pragma.kind for pragma in found] == [TYPE_IGNORE, NOQA]
    assert [pragma.reason for pragma in found] == ['', '']


def test_each_pragma_is_located_at_its_own_hash():
    source = 'value = 1  # type: ignore[x]  # noqa: E501 long\n'
    found = read_pragmas(source.encode('utf-8'))
    assert [(pragma.line, pragma.column) for pragma in found] == [
        (1, source.index('# type') + 1),
        (1, source.index('# noqa') + 1),
    ]


def test_text_that_mentions_a_pragma_is_not_one():
    assert read_pragmas(b'x = 1  # see the noqa rules\n') == []
    assert read_pragmas(b'x = 1  # a type: ignore would hide it\n') == []
    assert read_pragmas(b'x = 1  # noqarious\n') == []
    assert read_pragmas(b'x = 1  # type: ignored\n') == []


def test_a_pragma_in_a_string_is_not_a_comment():
    assert read_pragmas(b"x = '# noqa: E501'\n") == []


def test_only_a_reasoned_noqa_naming_the_code_suppresses_it():
    reasoned = Pragma(NOQA, 1, 1, ('E501', 'OGC131'), 'held')
    assert reasoned.suppresses('OGC131')
    assert not reasoned.suppresses('OGC141')
    assert not Pragma(NOQA, 1, 1, ('OGC131',), '').suppresses('OGC131')
    assert not Pragma(NOQA, 1, 1, (), 'blanket').suppresses('OGC131')
    assert not Pragma(TYPE_IGNORE, 1, 1, ('OGC131',), 'held').suppresses('OGC131')


def test_a_following_comment_with_no_words_is_not_a_reason():
    (pragma,) = read_pragmas(b'x = 1  # noqa: E501  # --\n')
    assert pragma.reason == ''
