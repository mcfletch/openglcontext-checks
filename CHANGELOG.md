# Changelog

Notable changes to `openglcontext-checks`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [semantic versioning](https://semver.org/); `0.x` makes no
compatibility promise.

## [0.1.0a1] - unreleased

### Added

- A mypy plugin, `openglcontext_checks.mypy_plugin`: a checked type made or
  subclassed outside the module defining it is an error
  (`checked-construction`), and in the `loader` scope a file opened at a path
  whose type is not a contained path is an error (`unchecked-open`).
  OpenGLContext's checked types are refused in every project; the
  `checked-types` and `contained-paths` keys add a project's own.
- The rules OGC131 (`id()` as a key), OGC141 (GL call in `__del__`), OGC161
  (configuration or I/O at import), OGC201 (suppression without a reason),
  and, in the `test` scope, OGC221 (skip inside an `except`), OGC222 (test
  with no assertion) and OGC223 (`pass` in a test's handler). Each carries
  `VALID` and `INVALID` examples that the suite runs.
- `oglc-check [paths]`, printing `path:line:column: CODE message`, with
  `--statistics`, `--select`, `--ignore`, `--no-cache` and `--jobs`. Exit
  status 0 clean, 1 findings, 2 usage, configuration or parse error.
- `--force-exclude`: a path named on the command line that is outside the
  project, outside `paths` or excluded is passed over, as a run with no
  arguments would pass over it.
- Configuration in `[tool.openglcontext-checks]`: `paths`, `select`,
  `ignore`, `exclude`, `per-file-ignores` and `scopes`.
- Suppression by `# noqa: CODE reason`, in ruff's syntax; a suppression with
  no reason does not suppress.
- A per-project result cache in `.oglc-check-cache/`, keyed on each file's
  bytes, the package's own source and the settings that apply to it.
- Checking across worker processes for a run of 48 or more files to parse.
- A pytest entry point, `-p openglcontext_checks.pytest_plugin`: one item per
  selected rule in a run of the suite.
- OGC222 follows a test's calls to helpers defined in its own module, so a
  test whose assertion is in `_close(found, wanted)` or `self._is_inverse(m)`
  is not reported.
- The `script` scope, for a project's programs run by path, which OGC161
  does not run on; a rule declares a scope it does not run in as
  `exempt_scope`. A scope's glob with a leading `!` takes paths out of it.
- OGC131 does not report a table that exists for one call (a local name
  bound only to a container the function makes, used only in place), a set
  or dict display compared or measured and dropped, or a lookup whose entry
  is compared by identity with the keyed object, directly or through the
  name it is assigned to.
- OGC201 reports text written straight after a `# type: ignore`'s codes,
  which mypy rejects as an invalid comment; a type-ignore's reason goes in a
  comment of its own after it.
- The rules OGC101 (bare conversion of a document value), OGC102 (decode
  before a size check) and OGC111 (raw opener on an unconfined path), in the
  new `loader` scope; OGC121 (file written in place), outside the `test`
  scope; and OGC151 (GL state change not restored), in the new `pass`
  scope. The `loader` and `pass` scopes are empty until a project names
  them.
- The `sanctioned` configuration key: a project's own API for the rules that
  point at one, by rule code and qualified name, in place of OpenGLContext's.
- OGC141 counts a call to a parameter whose default is an OpenGL function
  (`def __del__(self, glDeleteLists=glDeleteLists)`).
