"""OGC232: an override that renames an inherited parameter.

The rule end to end, and the index that resolves a base class through its
module's imports, including one defined in another module read from disk.
"""

import textwrap

from openglcontext_checks.config import load_config
from openglcontext_checks.engine import check_source, parse_module
from openglcontext_checks.rules.ogc232_override_renames_param import (
    Index,
    Renamed,
    dotted_module_name,
    find_overrides,
)
from openglcontext_checks.runner import check_files, discover

BASE = """
    class Base:
        def end(self, over, now):
            pass
"""

CHILD = """
    class Child(Base):
        def end(self, _over, _now):
            pass
"""


def _project(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "p"\n')
    return tmp_path


def _check(root, **options):
    config = load_config(str(root))
    return check_files(config, discover(config, None, str(root)), cwd=str(root), **options)


def _index(tmp_path, files):
    """An `Index` over the given project-relative files, and the names shown."""
    modules = []
    shown = {}
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = textwrap.dedent(source)
        path.write_text(text, encoding='utf-8')
        modules.append(parse_module(text.encode('utf-8'), str(path)))
        shown[str(path)] = name
    return Index(modules), shown


def test_a_same_module_override_is_reported_on_the_child():
    source = 'class Base:\n    def end(self, over):\n        pass\n\n\n' + (
        'class Child(Base):\n    def end(self, _over):\n        pass\n'
    )
    findings = check_source(source, codes=['OGC232'])
    assert [finding.line for finding in findings] == [7]
    assert findings[0].message == 'Child.end overrides Base.end: over -> _over'


def test_a_rename_that_is_not_an_underscore_prefix_is_not_reported():
    source = 'class Base:\n    def end(self, over):\n        pass\n\n\n' + (
        'class Child(Base):\n    def end(self, renamed):\n        pass\n'
    )
    assert check_source(source, codes=['OGC232']) == []


def test_a_base_named_as_a_parameter_is_not_an_override():
    source = 'def build(Base):\n    class Child(Base):\n        def end(self, _over):\n            pass\n'
    assert check_source(source, codes=['OGC232']) == []


def test_a_suppressing_pragma_with_a_reason_silences_the_finding():
    source = (
        'class Base:\n    def end(self, over):\n        pass\n\n\n'
        'class Child(Base):\n'
        '    def end(self, _over):  # noqa: OGC232 the base signature is kept\n'
        '        pass\n'
    )
    assert check_source(source, codes=['OGC232']) == []


def test_a_suppressing_pragma_without_a_reason_does_not_silence_it():
    source = (
        'class Base:\n    def end(self, over):\n        pass\n\n\n'
        'class Child(Base):\n'
        '    def end(self, _over):  # noqa: OGC232\n'
        '        pass\n'
    )
    assert [finding.line for finding in check_source(source, codes=['OGC232'])] == [7]


def test_an_override_of_a_base_in_another_module_is_reported(tmp_path):
    root = _project(tmp_path)
    package = root / 'pkg'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'base.py').write_text('class Base:\n    def end(self, over, now):\n        pass\n')
    (package / 'child.py').write_text(
        'from pkg.base import Base\n\n\nclass Child(Base):\n    def end(self, _over, _now):\n'
        '        pass\n'
    )
    report = _check(root)
    assert [path for path, _finding in report.findings] == ['pkg/child.py']
    _path, finding = report.findings[0]
    assert finding.line == 5
    assert finding.message == ('Child.end overrides Base.end: over -> _over, now -> _now')


def test_the_second_run_reports_the_same_cross_module_finding(tmp_path):
    root = _project(tmp_path)
    package = root / 'pkg'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'base.py').write_text('class Base:\n    def end(self, over):\n        pass\n')
    (package / 'child.py').write_text(
        'from pkg.base import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n'
    )
    first = _check(root)
    second = _check(root)
    assert second.parsed == 0
    assert second.findings == first.findings


def test_a_change_to_the_base_file_reparses_the_child(tmp_path):
    root = _project(tmp_path)
    package = root / 'pkg'
    package.mkdir()
    (package / '__init__.py').write_text('')
    base = package / 'base.py'
    base.write_text('class Base:\n    def end(self, over):\n        pass\n')
    (package / 'child.py').write_text(
        'from pkg.base import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n'
    )
    first = _check(root)
    assert [path for path, _finding in first.findings] == ['pkg/child.py']
    base.write_text('class Base:\n    def end(self, _over):\n        pass\n')
    second = _check(root)
    assert second.parsed == 2
    assert second.findings == []


def test_a_file_that_ignores_the_rule_reports_nothing(tmp_path):
    root = _project(tmp_path)
    (root / 'pyproject.toml').write_text(
        '[project]\nname = "p"\n\n[tool.openglcontext-checks]\nignore = ["OGC232"]\n'
    )
    (root / 'base.py').write_text('class Base:\n    def end(self, over):\n        pass\n')
    (root / 'child.py').write_text(
        'from base import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n'
    )
    report = _check(root)
    assert report.findings == []


def test_dotted_module_name_of_a_top_level_module(tmp_path):
    path = tmp_path / 'mod.py'
    path.write_text('', encoding='utf-8')
    assert dotted_module_name(str(path)) == 'mod'


def test_dotted_module_name_of_a_package_module(tmp_path):
    for name in ('pkg/__init__.py', 'pkg/sub/__init__.py', 'pkg/sub/mod.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('', encoding='utf-8')
    assert dotted_module_name(str(tmp_path / 'pkg/sub/mod.py')) == 'pkg.sub.mod'


def test_dotted_module_name_of_a_package(tmp_path):
    path = tmp_path / 'pkg/__init__.py'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('', encoding='utf-8')
    assert dotted_module_name(str(path)) == 'pkg'


def test_dotted_module_name_without_a_py_suffix(tmp_path):
    path = tmp_path / 'mod'
    path.write_text('', encoding='utf-8')
    assert dotted_module_name(str(path)) == 'mod'


def test_an_override_that_renames_a_parameter_is_reported(tmp_path):
    index, shown = _index(tmp_path, {'m.py': BASE + CHILD})
    found = find_overrides(index, shown)
    assert len(found) == 1
    assert found[0].renamed == (Renamed('over', '_over'), Renamed('now', '_now'))
    assert found[0].child_name == 'Child.end'
    assert found[0].base_name == 'Base.end'
    assert found[0].child_path == 'm.py'


def test_an_override_that_keeps_the_names_is_not_reported(tmp_path):
    source = (
        BASE
        + """
        class Child(Base):
            def end(self, over, now):
                pass
    """
    )
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_a_method_with_no_base_is_not_reported(tmp_path):
    index, shown = _index(tmp_path, {'m.py': 'class C:\n    def go(self, _x):\n        pass\n'})
    assert find_overrides(index, shown) == []


def test_only_the_renamed_parameter_is_reported(tmp_path):
    source = """
        class Base:
            def go(self, a, b):
                pass

        class Child(Base):
            def go(self, a, _b):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found[0].renamed == (Renamed('b', '_b'),)


def test_a_keyword_only_parameter_is_reported(tmp_path):
    source = """
        class Base:
            def go(self, *, count):
                pass

        class Child(Base):
            def go(self, *, _count):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found[0].renamed == (Renamed('count', '_count'),)


def test_a_vararg_and_a_kwarg_are_reported(tmp_path):
    source = """
        class Base:
            def go(self, *args, **kwargs):
                pass

        class Child(Base):
            def go(self, *_args, **_kwargs):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found[0].renamed == (Renamed('args', '_args'), Renamed('kwargs', '_kwargs'))


def test_a_base_parameter_that_already_has_an_underscore_is_not_reported(tmp_path):
    source = """
        class Base:
            def go(self, _private):
                pass

        class Child(Base):
            def go(self, __private):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_a_parameter_renamed_without_an_underscore_is_not_reported(tmp_path):
    source = """
        class Base:
            def go(self, value):
                pass

        class Child(Base):
            def go(self, other):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_a_base_imported_from_another_module_is_reported(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/child.py': (
            'from pkg.base import Base\n\n\n'
            'class Child(Base):\n    def end(self, _over):\n        pass\n'
        ),
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert len(found) == 1
    assert found[0].base_path == 'pkg/base.py'
    assert found[0].child_path == 'pkg/child.py'


def test_a_base_found_by_a_lookup_callable_is_reported(tmp_path):
    library = tmp_path / 'lib'
    library.mkdir()
    (library / '__init__.py').write_text('')
    (library / 'base.py').write_text('class Base:\n    def end(self, over):\n        pass\n')
    child = tmp_path / 'child.py'
    module = parse_module(
        b'from lib.base import Base\n\n\n'
        b'class Child(Base):\n    def end(self, _over):\n        pass\n',
        str(child),
    )
    asked = []

    def find(name):
        asked.append(name)
        return str(library / 'base.py') if name == 'lib.base' else None

    index = Index([module], find)
    found = find_overrides(index, {str(child): 'child.py'})
    assert [override.child_name for override in found] == ['Child.end']
    assert asked == ['lib.base']


def test_a_base_file_that_cannot_be_read_is_not_resolved(tmp_path):
    child = tmp_path / 'child.py'
    module = parse_module(
        b'from lib.base import Base\n\n\n'
        b'class Child(Base):\n    def end(self, _over):\n        pass\n',
        str(child),
    )
    missing = str(tmp_path / 'lib' / 'base.py')
    index = Index([module], lambda name: missing if name == 'lib.base' else None)
    assert find_overrides(index, {str(child): 'child.py'}) == []


def test_a_base_file_that_cannot_be_parsed_is_not_resolved(tmp_path):
    library = tmp_path / 'lib'
    library.mkdir()
    (library / '__init__.py').write_text('')
    (library / 'base.py').write_text('def (:\n')
    child = tmp_path / 'child.py'
    module = parse_module(
        b'from lib.base import Base\n\n\n'
        b'class Child(Base):\n    def end(self, _over):\n        pass\n',
        str(child),
    )
    index = Index([module], lambda _name: str(library / 'base.py'))
    assert find_overrides(index, {str(child): 'child.py'}) == []


def test_a_second_base_in_a_loaded_module_is_not_read_again(tmp_path):
    library = tmp_path / 'lib'
    library.mkdir()
    (library / '__init__.py').write_text('')
    (library / 'base.py').write_text('class Base:\n    def end(self, over):\n        pass\n')
    child = tmp_path / 'child.py'
    module = parse_module(
        b'from lib.base import Base\n'
        b'from lib.base import Ghost\n\n\n'
        b'class Child(Base):\n    def end(self, _over):\n        pass\n\n\n'
        b'class Other(Ghost):\n    def end(self, _over):\n        pass\n',
        str(child),
    )
    asked = []

    def find(name):
        asked.append(name)
        return str(library / 'base.py') if name == 'lib.base' else None

    index = Index([module], find)
    found = find_overrides(index, {str(child): 'child.py'})
    assert [override.child_name for override in found] == ['Child.end']
    assert asked == ['lib.base', 'lib']


def test_a_relative_import_base_is_reported(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/child.py': 'from .base import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n',
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert len(found) == 1
    assert found[0].base_name == 'Base.end'


def test_a_class_reexported_by_a_package_is_not_resolved(tmp_path):
    files = {
        'pkg/__init__.py': 'from .base import Base\n',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/child.py': (
            'from . import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n'
        ),
    }
    index, shown = _index(tmp_path, files)
    assert find_overrides(index, shown) == []


def test_a_base_imported_relatively_by_a_package_is_reported(tmp_path):
    files = {
        'pkg/__init__.py': (
            'from .base import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n'
        ),
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Base.end'


def test_a_two_level_relative_import_is_resolved(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/sub/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/sub/child.py': 'from ..base import Base\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n',
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Base.end'


def test_a_relative_import_past_the_top_is_not_resolved(tmp_path):
    source = """
        from ...nowhere import Thing

        class Child(Thing):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_a_dotted_base_with_an_unresolved_value_is_not_resolved(tmp_path):
    source = """
        class Child(missing.Thing):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_a_relative_import_without_a_module_is_not_resolved(tmp_path):
    source = """
        from . import Missing

        class Child(Missing):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_the_same_star_imported_class_twice_is_resolved(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/one.py': 'from pkg.base import *\n',
        'pkg/mod.py': (
            'from pkg.base import *\nfrom pkg.one import *\n\n\n'
            'class Child(Base):\n    def end(self, _over):\n        pass\n'
        ),
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Base.end'


def test_a_base_vararg_with_no_child_vararg_is_not_reported(tmp_path):
    source = """
        class Base:
            def go(self, first, second, *args, **kwargs):
                pass

        class Child(Base):
            def go(self, _first):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found[0].renamed == (Renamed('first', '_first'),)


def test_the_base_cache_is_reused_for_a_class_with_two_methods(tmp_path):
    source = """
        class Base:
            def one(self, a):
                pass

            def two(self, b):
                pass

        class Child(Base):
            def one(self, _a):
                pass

            def two(self, _b):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert {item.child_name for item in found} == {'Child.one', 'Child.two'}


def test_a_class_base_imported_by_name_is_resolved(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/mod.py': 'from pkg.base import Base as Parent\n\n\nclass Child(Parent):\n    def end(self, _over):\n        pass\n',
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Base.end'


def test_a_module_qualified_base_is_resolved(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/mod.py': 'from pkg import base\n\n\nclass Child(base.Base):\n    def end(self, _over):\n        pass\n',
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Base.end'


def test_a_star_imported_base_is_resolved(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/base.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/mod.py': 'from pkg.base import *\n\n\nclass Child(Base):\n    def end(self, _over):\n        pass\n',
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Base.end'


def test_an_ambiguous_star_import_is_not_resolved(tmp_path):
    files = {
        'pkg/__init__.py': '',
        'pkg/one.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/two.py': 'class Base:\n    def end(self, over):\n        pass\n',
        'pkg/mod.py': (
            'from pkg.one import *\nfrom pkg.two import *\n\n\n'
            'class Child(Base):\n    def end(self, _over):\n        pass\n'
        ),
    }
    index, shown = _index(tmp_path, files)
    assert find_overrides(index, shown) == []


def test_a_nested_class_base_is_resolved(tmp_path):
    source = """
        class Outer:
            class Base:
                def end(self, over):
                    pass

        class Child(Outer.Base):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found and found[0].base_name == 'Outer.Base.end'


def test_a_base_outside_the_project_is_not_resolved(tmp_path):
    source = """
        import collections

        class Child(collections.OrderedDict):
            def __init__(self, *args, **kwargs):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_an_unresolvable_base_expression_is_not_resolved(tmp_path):
    source = """
        class Child(Factory[int]):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_an_unbound_name_is_not_a_base(tmp_path):
    source = """
        class Child(Unknown):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    assert find_overrides(index, shown) == []


def test_the_base_naming_the_parameter_without_an_underscore_is_used(tmp_path):
    source = """
        class A:
            def end(self, over):
                pass

        class B(A):
            def end(self, _over):
                pass

        class C(B):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    by_name = {item.child_name: item for item in found}
    assert by_name['B.end'].base_name == 'A.end'
    assert by_name['C.end'].base_name == 'A.end'


def test_multiple_inheritance_takes_the_first_definer_in_the_mro(tmp_path):
    source = """
        class Left:
            def end(self, over):
                pass

        class Right:
            def end(self, over):
                pass

        class Child(Left, Right):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found[0].base_name == 'Left.end'


def test_an_inconsistent_hierarchy_is_still_reported(tmp_path):
    source = """
        class X:
            def end(self, over):
                pass

        class Y:
            def end(self, over):
                pass

        class A(X, Y):
            pass

        class B(Y, X):
            pass

        class C(A, B):
            def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found and found[0].base_name in ('X.end', 'Y.end')


def test_a_base_cycle_terminates(tmp_path):
    source = """
        class A(B):
            def end(self, _over):
                pass

        class B(A):
            def end(self, over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert all(item.base_name != item.child_name for item in found)
    find_overrides(index, shown)  # must not recurse forever


def test_an_async_override_is_reported(tmp_path):
    source = """
        class Base:
            def end(self, over):
                pass

        class Child(Base):
            async def end(self, _over):
                pass
    """
    index, shown = _index(tmp_path, {'m.py': source})
    found = find_overrides(index, shown)
    assert found and found[0].renamed == (Renamed('over', '_over'),)


def test_findings_are_sorted_by_path_and_line(tmp_path):
    files = {
        'b.py': BASE + CHILD,
        'a.py': BASE + CHILD,
    }
    index, shown = _index(tmp_path, files)
    found = find_overrides(index, shown)
    assert [item.child_path for item in found] == ['a.py', 'b.py']
