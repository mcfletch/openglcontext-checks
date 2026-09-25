"""OGC131, beyond its own examples."""

from openglcontext_checks.engine import check_source


def _found(source):
    return check_source(source, codes=['OGC131'])


def test_the_message_names_the_object_and_the_alternatives():
    (finding,) = _found('cache[id(mesh.positions)] = fitted\n')
    assert finding.code == 'OGC131'
    assert (finding.line, finding.column) == (1, 7)
    assert 'id(mesh.positions)' in finding.message
    assert 'WeakKeyDictionary' in finding.message


def test_an_id_held_under_another_name_is_not_a_key_here():
    """Only the shapes that key a table are flagged; a plain name is not one."""
    assert _found('key = id(node)\n') == []


def test_a_call_with_other_than_one_argument_is_not_the_builtin_s_shape():
    assert _found('cache[id()] = 1\ncache[id(a, b)] = 2\n') == []


def test_an_imported_id_is_not_the_builtin():
    assert _found('from ids import id\ncache[id(node)] = 1\n') == []


def test_a_statement_holding_a_different_object_is_still_flagged():
    assert len(_found('cache[id(node)] = (other, value)\n')) == 1


def test_an_id_compared_against_a_computed_collection_is_a_lookup():
    assert len(_found('found = id(node) not in live_ids()\n')) == 1


def test_an_id_in_an_ordinary_call_is_not_a_key():
    assert _found('register(id(node))\nitems.index(id(node))\n') == []


def test_an_id_assigned_to_several_names_is_not_an_attribute_store():
    assert _found('a = b = id(node)\n') == []


def test_a_starred_display_can_hold_the_object():
    assert _found('cache[id(node)] = [*(node, value)]\n') == []


def test_only_the_statement_s_own_expressions_can_hold_the_object():
    """A block's body is other statements, with objects of their own."""
    source = 'if id(node) in seen:\n    table = {1: node}\n'
    assert [finding.line for finding in _found(source)] == [1]


def test_an_augmented_assignment_is_searched_for_the_object():
    assert _found('counts[id(node)] += (node,)\n') == []


def test_a_long_expression_is_shortened_in_the_message():
    (finding,) = _found('cache[id(self.scene.children[0].geometry.coordinates)] = 1\n')
    assert 'id(self.scene.children[0].geometry.coord...)' in finding.message


def test_an_id_in_a_list_display_is_not_a_key():
    assert _found('ids = [id(a), id(b)]\n') == []
