"""OGC111, beyond its own examples."""

import pytest

from openglcontext_checks.engine import check_source


def _found(source, **options):
    options.setdefault('scopes', ['loader'])
    return check_source(source, codes=['OGC111'], **options)


def _in_function(body, parameters='base, name, names, table, self'):
    lines = ''.join('    %s\n' % (line,) for line in body.splitlines())
    return 'import os, pathlib, numpy\nfrom PIL import Image\ndef f(%s):\n%s' % (parameters, lines)


def test_the_message_names_the_opener_the_part_and_the_resolver():
    (finding,) = _found(_in_function('return open(os.path.join(base, name))'))
    assert (finding.line, finding.column) == (4, 12)
    assert 'open() opens a path joined from name' in finding.message
    assert 'OpenGLContext.loaders.tiles3d.fetch.beside' in finding.message


def test_a_project_names_its_own_resolver():
    own = {'OGC111': ('game.files.inside',)}
    (finding,) = _found(_in_function('return open(base + name)'), sanctioned=own)
    assert finding.message.endswith('(game.files.inside)')


def test_only_the_loader_scope_is_checked():
    assert _found(_in_function('return open(base + name)'), scopes=[]) == []


@pytest.mark.parametrize(
    'body',
    [
        'return open(os.path.join(base, name))',
        'return open(os.path.abspath(os.path.join(base, name)), "rb")',
        'return open(base + "/" + name)',
        'return open("%s/%s" % (base, name))',
        'return open("/data/%s" % name)',
        'return open("{}/{}".format(base, name))',
        'return open(f"{base}/{name}")',
        'return Image.open(pathlib.Path(base) / name)',
        'return numpy.load(pathlib.Path(base, name))',
        'return open(os.path.join(base, *names))',
        'return open(table["texture"])',
        'return open(table.get("texture"))',
        'where = os.path.join(base, name)\nreturn open(where)',
        'where = base\nwhere += name\nreturn open(where)',
        'for member in names:\n    open(os.path.join(base, member))',
        'return open(os.path.join(base, self.name))',
        'return open(file=os.path.join(base, name))',
        'where: str = os.path.join(base, name)\nreturn open(where)',
        'if (where := base + name):\n    return open(where)',
        'self.cache = name\nfirst, *rest = names\nwhere = base + name\nreturn open(where)',
        'def inner():\n    where = "x"\nwhere = base + name\nreturn open(where)',
        'return open(os.path.join(base, name) if names else "x.glb")',
        'return open("x.glb" if names else os.path.join(base, name))',
        'return open(os.path.join(os.path.join(base, name), "x.glb"))',
    ],
)
def test_a_path_built_from_a_part_the_source_does_not_fix_is_reported(body):
    assert len(_found(_in_function(body))) == 1


@pytest.mark.parametrize(
    'body',
    [
        'return open(name)',
        'return open(self.path)',
        'return open("model.glb")',
        'return open(os.path.join(base, "ground.glb"))',
        'return open(os.path.join(base, SIDECAR))',
        'return open(os.path.join(base, os.pardir, "x"))',
        'for member in ("a.glb", "b.glb"):\n    open(os.path.join(base, member))',
        'for member in NAMES:\n    open(os.path.join(base, member))',
        'suffix = ".json"\nreturn open(base + suffix)',
        'return open(resolver.resolve(name))',
        'return open()',
        'return open(*names)',
        'return open(mode="rb")',
        'return open(__file__)',
        'from os import sep\nreturn open(base + sep)',
        'return "%d" % 3',
        'return open(base.format(name))',
        'return open(base - name)',
        'return open(f"{base}")',
        'return open(os.path.join(base, f"{3}.glb"))',
        'return open(os.path.join(base, "a" + "b"))',
        'return open(os.path.join(base, ("a", "b")[0]))',
    ],
)
def test_a_parameter_a_fixed_name_or_another_call_is_not_reported(body):
    assert _found('SIDECAR = "x.json"\nNAMES = ("a",)\n' + _in_function(body)) == []


def test_a_name_reassigned_from_a_parameter_keeps_the_parameter():
    body = 'if names:\n    name = "fixed.glb"\nreturn open(os.path.join(base, name))'
    assert len(_found(_in_function(body))) == 1


def test_a_name_assigned_a_fixed_value_only_is_fixed():
    body = 'member = "fixed.glb"\nreturn open(os.path.join(base, member))'
    assert _found(_in_function(body)) == []


def test_a_name_assigned_from_a_call_is_the_call_s_result():
    body = 'where = resolver.resolve(name)\nreturn open(where)'
    assert _found(_in_function(body)) == []


def test_a_name_unpacked_from_a_literal_pair_is_followed():
    body = 'first, second = "a.glb", name\nreturn open(base + second)'
    assert len(_found(_in_function(body))) == 1
    body = 'first, second = "a.glb", "b.glb"\nreturn open(base + second)'
    assert _found(_in_function(body)) == []


def test_a_name_bound_by_with_or_in_a_comprehension_is_followed():
    body = '[open(base + member) for member in names]'
    assert len(_found(_in_function(body))) == 1
    body = 'with opener() as member:\n    return open(base + member)'
    assert len(_found(_in_function(body))) == 1


def test_a_path_built_at_module_level_from_module_names_is_fixed():
    assert _found('import os\nROOT = "/x"\nNAME = "y"\nopen(os.path.join(ROOT, NAME))\n') == []


def test_a_name_that_refers_to_itself_does_not_loop():
    body = 'where = base\nwhere = where + "x"\nreturn open(os.path.join(base, where))'
    assert len(_found(_in_function(body))) == 1


def test_a_lambda_s_parameter_is_a_parameter():
    source = 'import os\nopener = lambda base, name: open(os.path.join(base, name))\n'
    assert len(_found(source)) == 1


def test_a_method_s_own_name_in_a_class_body_is_not_a_local():
    source = (
        'import os\n'
        'class Reader:\n'
        '    name = "x"\n'
        '    def read(self, base):\n'
        '        return open(os.path.join(base, name))\n'
    )
    assert _found(source) == []
