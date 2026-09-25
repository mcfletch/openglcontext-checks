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


def _in_function(body):
    return _found('def walk(nodes):\n' + ''.join('    %s\n' % line for line in body))


def test_a_table_unpacked_from_a_tuple_of_new_containers_is_the_call_s_own():
    assert _in_function(['found, seen = [], {id(nodes): 1}', 'return found']) == []


def test_a_table_unpacked_from_something_else_is_not_known_to_be_new():
    assert len(_in_function(['found, seen = pair', 'seen.add(id(nodes))'])) == 1


def test_a_name_bound_by_an_import_is_not_the_call_s_own():
    source = 'from registry import TABLE\ndef walk(node):\n    TABLE[id(node)] = 1\n'
    assert len(_found(source)) == 1


def test_a_container_made_with_keywords_is_not_known_to_be_empty():
    assert len(_in_function(['seen = dict(**others)', 'seen[id(nodes)] = 1'])) == 1


def test_a_table_handed_on_through_a_boolean_expression_escapes():
    body = ['seen = set()', 'seen.add(id(nodes))', 'kept = seen or other']
    assert len(_in_function(body)) == 1


def test_a_table_compared_with_another_stays_in_the_call():
    body = ['seen = set()', 'seen.add(id(nodes))', 'same = seen == other']
    assert _in_function(body) == []


def test_a_table_from_any_other_call_is_not_known_to_be_new():
    assert len(_in_function(['seen = registry()', 'seen.add(id(nodes))'])) == 1


def test_a_table_walked_after_it_is_filled_stays_in_the_call():
    body = [
        'import collections',
        'seen = collections.defaultdict(list, [])',
        'seen[id(nodes)].append(1)',
        'for key in seen:',
        '    print(key)',
    ]
    assert _in_function(body) == []
