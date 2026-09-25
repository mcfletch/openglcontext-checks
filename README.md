# openglcontext-checks

Static checks for defect classes found repeatedly in reviews of the
OpenGLContext stack: identity-keyed caches, GL calls from finalisers,
configuration read at import, suppressions with no reason, and tests that
cannot fail. Each rule has a stable code, `OGC` and three digits, and decides
from a module's syntax tree, what its names are bound to, and its comment
tokens. The package needs nothing beyond the standard library (and `tomli` on
Python 3.10), so a project installs it without the engine.

```console
$ pip install openglcontext-checks
$ oglc-check
src/game/cache.py:41:14: OGC131 id(mesh) as a key: the id is reused once the object is collected, so the entry can answer a different object; key on the object (a WeakKeyDictionary) or hold it in the entry
tests/test_render.py:12:1: OGC222 test_draws has no assertion: it passes whatever the code does, unless something raises; assert on the result, or use pytest.raises
```

## Running it

```console
$ oglc-check                        # the project's configured paths
$ oglc-check src/pkg/module.py      # just these files or directories
$ oglc-check --force-exclude FILE   # FILE, if a run with no arguments would check it
$ oglc-check --statistics           # how many findings of each rule
$ oglc-check --select OGC131,OGC2   # these rules only (codes or prefixes)
$ oglc-check --ignore OGC222        # all but these
$ oglc-check --no-cache             # neither read nor write the result cache
```

Findings print as `path:line:column: CODE message`, sorted by path and line,
with paths relative to the current directory. `--statistics` prints a count
per rule instead. The exit status is 0 when there are no findings, 1 when
there are, and 2 for a usage or configuration error or a file that does not
parse; a file that does not parse is named on standard error.

`--select` replaces the configured selection and `--ignore` adds to the
configured ignores. `--jobs N` sets the number of worker processes; a run
with 48 or more files to parse spreads them over up to eight processes by
default, and a smaller run uses one.

Over the 514 modules of `OpenGLContext/` (138,000 lines) on a 32-core machine,
a run with nothing cached takes 0.24 s (0.87 s in one process), and a run
answered from the cache takes 0.06 s.

## Configuration

The project is the nearest directory, at or above the current one, holding a
`pyproject.toml`, and settings are read from `[tool.openglcontext-checks]` in
that file. Its directory is the project root: configured paths and globs are
relative to it. Where that file has no table, every setting takes its default;
a table in an enclosing project (a workspace root around several projects, say)
is not used, since its paths are relative to another root.

```toml
[tool.openglcontext-checks]
paths = ["src", "tests"]              # what a run with no arguments checks; default ["."]
select = ["OGC131", "OGC2"]           # codes or prefixes; default every rule
ignore = ["OGC222"]                   # taken out of select
exclude = ["src/generated"]           # not checked, beyond the defaults below

[tool.openglcontext-checks.per-file-ignores]
"scripts/**" = ["OGC161"]             # not run on the files the glob matches

[tool.openglcontext-checks.scopes]
test = ["tests/**", "**/test_*.py"]   # the modules the test rules run on
script = ["tools/*.py", "!tools/_*.py"]  # programs run by path; not OGC161
```

A path is in a scope when it matches one of the scope's globs and none of
the globs written with a leading `!`. The `test` scope, which OGC221 to
OGC223 run in, defaults to `tests/**`, `**/test_*.py`, `**/*_test.py` and
`**/conftest.py`. The `script` scope is empty unless a project names its
programs: files run by path, whose module level is their start-up, which
OGC161 does not run on. An unknown key, an
unknown rule code or scope, or a value of the wrong type is a configuration
error, and the run exits 2 naming it.

Globs are matched against the path relative to the project root, written
with `/`. A glob with no `/` matches any one component, so `build` matches a
directory of that name at any depth and `test_*.py` a file anywhere. A glob
with a `/` is anchored at the root and also matches everything beneath a
directory it names. `*` and `?` stay within one component, `[...]` is a
character class, and a `**` component matches any number of directories.

Files and directories whose names start with a dot are not checked
(version control, virtualenvs, tool caches, git worktrees), nor `venv`,
`__pycache__`, `*.egg-info`, `build`, `_build`, `dist`, `node_modules` and
`site-packages`. The package does not read `.gitignore`. A path named on the
command line or in `paths` is checked even when an exclusion matches it;
exclusions apply to what is found beneath it.

`--force-exclude` holds the paths named on the command line to the
configuration as well: a path outside the project, outside `paths`, or
matched by an exclusion is passed over. An editor or a hook that hands over
every file it touched uses it, so that what it checks is what the project's
own run checks.

## Suppressing a finding

A finding is suppressed by a `# noqa` comment on the reported line that names
its code and gives a reason:

```python
cache[id(node)] = value  # noqa: OGC131 the cache is cleared with the scene that owns every node
```

The syntax is ruff's, so one comment can serve both tools:
`# noqa: E501, OGC131 reason`. A `# noqa` with no reason, or a bare `# noqa`,
does not suppress an OGC finding, and OGC201 reports it. A project that runs
ruff's RUF100 (unused `noqa`) tells ruff the codes are another tool's with
`external = ["OGC"]` in `[tool.ruff.lint]`.

## The result cache

Each project keeps the findings of its last run in `.oglc-check-cache/` in the
project root. An entry is keyed on the file's bytes, this package's own source
(so an edited rule in an editable install counts, not only a new version),
and the codes and scopes that apply to the file, so editing the file, changing
the package or changing the configuration each make it miss. An
unchanged file is not parsed again, and its stored findings are reported as
before. The cache file is replaced whole, through a temporary file and one
rename. The directory holds a `.gitignore` of `*`, so it stays out of version
control without an entry in the project's own `.gitignore`.

## In a pytest suite

```toml
[tool.pytest.ini_options]
addopts = "-p openglcontext_checks.pytest_plugin"
```

A run of the suite (pytest started with no paths) then includes one item per
selected rule, `oglc-check[OGC131]` and so on. The rules run once per session
over the project's configured paths with its settings and cache, and each
item fails listing its rule's findings. A file that does not parse fails
every item. `-k` and `-m` deselect the items like any others. A run naming its
own paths does not include them unless `--oglc-check` is given. The package
declares no `pytest11` entry point, so installing it changes no suite that has
not asked for the items.

## The rules

### OGC131: `id()` as a key

`id(x)`, alone or in a tuple, used as a subscript, a dict or set key, the
left side of `in`, the first argument of `get`, `setdefault`, `pop`, `add`,
`discard` or `remove`, or a value assigned to an attribute, where the same
statement does not also store `x`. An id is reused as soon as its object is
collected, and the table then answers a new object with the old one's entry.
Key on the object (a `WeakKeyDictionary` where the table should not keep it
alive), or hold the object in the entry and compare it on lookup.

Not reported: a table that exists for one call (a local name bound only to a
container made in the function, used only in place, never passed on,
returned, stored or read from a nested function), a set or dict display that
is compared or measured with `len` and dropped, and a lookup whose entry is
compared by identity with the object, directly (`table.get(id(x)) is x`) or
through the name it is assigned to (`entry[0] is x`).

```python
_FITS[id(positions)] = fitted          # OGC131
_FITS[id(positions)] = (positions, fitted)   # holds the object: not reported

entry = _FITS.get(id(positions))       # compared on lookup: not reported
if entry is None or entry[0] is not positions:
    ...

seen = set()                           # the call's own table: not reported
for node in walk(root):
    seen.add(id(node))
```

### OGC141: GL call in `__del__`

A call inside a `__del__` method to a function of `OpenGL.GL`, an
`OpenGL.GLES*` module or their `OpenGL.raw` forms, through any import form;
after a star import from one of those, an unbound name spelled `gl` and a
capital letter. A finaliser runs on whichever thread collects the object,
with whatever context is current there or none. Queue the release for the
context that owns the name, and delete it there.

```python
class Texture:
    def __del__(self):
        GL.glDeleteTextures([self.name])     # OGC141

class QueuedTexture:
    def __del__(self):
        PENDING_RELEASES.append(self.name)   # not reported
```

### OGC161: configuration or I/O at import

At module level or in a class body (decorators and default values included;
not in a function or lambda body, and not in the body of an
`if __name__ == '__main__':` or `if TYPE_CHECKING:` block): any use of
`os.environ`, `os.environb` or `sys.argv`, and calls to `os.getenv`,
`os.getenvb`, `os.putenv`, `os.unsetenv`, `locale.setlocale`, `open`,
`io.open`, `os.makedirs`, `os.mkdir`, `os.remove`, `os.unlink`, `os.rename`,
`os.replace`, `os.chdir` and every function of `shutil` and `subprocess`.
Names resolve through imports. The set is closed: other calls at import are
not reported. A value read at import is fixed before an application or a
test can set it. Read it where it is used, in a function.

A program run by path reads its configuration at module level by design, and
nothing in its syntax says it is one: a project lists its programs in the
`script` scope, and OGC161 does not run on them. A module with a `main()`
that a console-script entry point imports is not a program in this sense;
its start-up is `main()`.

```python
BACKEND = os.environ.get('BACKEND', 'glfw')      # OGC161

def backend():
    return os.environ.get('BACKEND', 'glfw')     # not reported
```

### OGC201: suppression without a reason

A `# noqa` or `# type: ignore` that names no code, or names codes with no
reason after them. A `# noqa`'s reason is at least one word after the codes,
optionally after `-`, `--`, `:` or a dash. A `# type: ignore`'s reason is a
comment of its own after it: mypy reports any other text after the codes as
an invalid comment, so text written there is reported too. Pragmas are read
from comment tokens, so text in a string is never one.

```python
import os  # noqa: F401                                   # OGC201
x = f()  # type: ignore                                   # OGC201 (bare)
x = f()  # type: ignore[attr-defined] the stubs lack it   # OGC201 (mypy rejects it)
x = f()  # type: ignore[attr-defined]  # the stubs lack it   # not reported
```

### OGC221: skip inside an `except`, in tests

A call to `pytest.skip`, `pytest.xfail` or `pytest.importorskip` in the body
of an `except` handler, in the `test` scope. The failure the handler caught is
reported as a skip. Use `pytest.importorskip` on its own for an optional
module, check for a capability before the code under test runs, or let the
exception fail the test.

```python
try:
    image = render()
except Exception:
    pytest.skip('render failed')        # OGC221
```

### OGC222: test with no assertion, in tests

A function pytest collects as a test (named `test*`, at module level or a
method of a module-level class) whose body, less nested definitions, has no
`assert`, no `raise` of an exception, no `pytest.raises`, `pytest.warns`,
`pytest.fail` or `pytest.deprecated_call`, and no call to a function or method
named `fail` or starting with `assert`, `check`, `expect` or `verify` (leading
underscores aside). A call to a helper defined in the same module counts when
the helper asserts, followed through the helpers it calls: a module-level
function called by the name its `def` binds, or a method called on the test's
`self`, from the test's class or a base class defined in the module. Such a
test fails only if something raises. Assert on the result, or use
`pytest.raises`; a helper from another module that asserts is named for it.

```python
def test_draws():
    draw()                              # OGC222

def test_draws():
    assert draw().covered > 0           # not reported
```

### OGC223: `pass` in a test's handler, in tests

An `except` handler anywhere inside a test function whose body is only `pass`
or `...`. The test passes whether or not the exception happened. Remove the
handler, use `pytest.raises`, or assert on what was caught.

```python
def test_teardown():
    try:
        close()
    except Exception:                   # OGC223
        pass
```

## Development

```console
$ pip install -e ".[dev]"
$ python -m coverage run -m pytest && python -m coverage report
$ ruff check . && ruff format --check .
$ mypy src/openglcontext_checks
$ oglc-check
```

The suite requires 100% line and branch coverage. It runs the package's own
pytest entry point, so it includes an item per rule over this project.

A rule is a module in `src/openglcontext_checks/rules/`: a `Rule` subclass
with a code, a name, a docstring saying what it flags, why and what to use
instead, and `VALID` and `INVALID` examples, which `tests/test_examples.py`
runs for every registered rule. It reports from `visit` (handed each node of
the types in `nodes`, from one walk shared by every rule) or `check_module`,
and resolves names through `module.symbols`. It is registered in
`rules/__init__.py`.

## Licence

BSD 3-Clause; see [LICENSE](LICENSE).
