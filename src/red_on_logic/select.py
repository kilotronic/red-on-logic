"""Which files are tests, which side of the swap a file is on, and which tests a diff touched."""

from __future__ import annotations

import ast
import fnmatch
import re
from collections.abc import Iterator, Sequence
from pathlib import PurePosixPath

HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")
PY_TEST = re.compile(r"^(test_.*|.*_test)\.py$")
JS_EXT = r"\.[cm]?[jt]sx?$"
JS_TEST = re.compile(r"(^|[.\-_])(test|spec)" + JS_EXT + r"|^test[\-_].*" + JS_EXT)
JS_ANY = re.compile(JS_EXT)
TEST_DIRS = frozenset(
    {
        "tests",
        "test",
        "__tests__",
        "spec",
        "testdata",
        "testing",
        "__fixtures__",
        "__mocks__",
        "__snapshots__",
    }
)
# Only source files go back to the base's version. Data, snapshots, docs, lockfiles and
# config (pyproject.toml, package.json, *.config.*, setup files) stay at the head's: a
# missing data file or an older runner config fails the base for a reason that is not the
# code under test.
CODE_EXT = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".vue",
        ".svelte",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
        ".ex",
        ".exs",
        ".erl",
        ".hs",
        ".ml",
        ".clj",
        ".lua",
        ".dart",
        ".sh",
        ".bash",
        ".zsh",
        ".pl",
    }
)
# Test-runner and build-tool config, wherever it sits: dot files, `<tool>.config.*` and the
# runners' setup files. `setup.py` and `noxfile.py` only at the repository root.
CONFIG_NAME = re.compile(
    r"^\.|^(jest|vitest|vite|babel|webpack|rollup|eslint|prettier|playwright|tsup|postcss"
    r"|tailwind|svelte|next|nuxt|astro|karma|cypress|stylelint|commitlint|lint-staged)\.config\."
    r"|^(jest|vitest|test)[.-]setup\.|^setupTests\.",
    re.I,
)
ROOT_CONFIG = frozenset({"setup.py", "noxfile.py"})
PY_NOISE = re.compile(r"^\s*(#.*)?$")
JS_NOISE = re.compile(r"^\s*(//.*|/\*.*|\*.*)?$")
JS_CALL = re.compile(r"""^\s*(?:test|it)(?:\.\w+)*\s*\(\s*(['"`])(.*?)\1""")


def hunk_lines(diff: str) -> set[int]:
    """Head-side line numbers one file's hunks touch, from `git diff -U0 -- <file>`.

    Only hunk headers are read, so quoted or prefixed file names cannot hide a change. A
    hunk that only deletes lines marks the line it lands on, so a test that lost lines
    counts as changed.
    """
    out: set[int] = set()
    for line in diff.splitlines():
        if match := HUNK.match(line):
            start, count = int(match[1]), int(match[2] or 1)
            out.update(range(start, start + count) if count else {max(start, 1)})
    return out


def matches_any(path: str, globs: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def is_test_file(path: str, extra: Sequence[str]) -> bool:
    """A file whose tests are judged: a pytest or JavaScript test file, or one of `extra`."""
    if matches_any(path, extra):
        return True
    p = PurePosixPath(path)
    if PY_TEST.match(p.name):
        return True
    if not JS_ANY.search(p.name):
        return False
    return bool(JS_TEST.search(p.name)) or "__tests__" in p.parts[:-1]


def is_test_side(path: str, extra: Sequence[str]) -> bool:
    """A file that keeps the pull request's version on the base run: tests and their support.

    Test files, anything under a test directory (helpers, fixtures, data) and conftest.py.
    Everything else is code and is put back to the base's version.
    """
    p = PurePosixPath(path)
    return (
        is_test_file(path, extra)
        or p.name == "conftest.py"
        or any(part in TEST_DIRS for part in p.parts[:-1])
    )


def is_code(path: str, extra: Sequence[str], code_paths: Sequence[str] = ()) -> bool:
    """A file the base run puts back to the base's version (or removes, when it is new):
    a source file that is neither test-side nor config, or one of `code_paths` (templates,
    SQL, rules: behaviour kept in files without a source extension)."""
    if is_test_side(path, extra):
        return False
    if matches_any(path, code_paths):
        return True
    p = PurePosixPath(path)
    return (
        p.suffix.lower() in CODE_EXT and not CONFIG_NAME.search(p.name) and path not in ROOT_CONFIG
    )


def _spans(body: list[ast.stmt], prefix: str) -> Iterator[tuple[str, tuple[int, int]]]:
    for node in body:
        if isinstance(node, ast.ClassDef):
            yield from _spans(node.body, f"{prefix}{node.name}::")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            yield f"{prefix}{node.name}", (start, node.end_lineno or node.lineno)


def _real(source: str, changed: set[int], noise: re.Pattern[str]) -> set[int]:
    lines = source.splitlines()
    return {n for n in changed if 0 < n <= len(lines) and not noise.match(lines[n - 1])}


def _all_or_each(spans: list[tuple[int, int] | None], real: set[int]) -> list[bool]:
    """A test whose own lines changed is touched. A changed line inside no test (an
    import, a helper, a fixture, a class attribute, a describe block) touches every test,
    since any of them may read it. A test whose lines are unknown counts as touched."""
    inside = {n for span in spans if span for n in range(span[0], span[1] + 1)}
    if real - inside:
        return [True for _ in spans]
    return [span is None or any(span[0] <= n <= span[1] for n in real) for span in spans]


def python_touched(source: str, keys: list[str], changed: set[int] | None) -> list[bool]:
    """For each test key (`test_a`, `TestC::test_d`), whether the diff changed it.

    None for `changed` means a new file: every test is new. Blank and comment-only lines
    touch nothing.
    """
    if changed is None:
        return [True for _ in keys]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [True for _ in keys]
    spans = dict(_spans(tree.body, ""))
    return _all_or_each([spans.get(k) for k in keys], _real(source, changed, PY_NOISE))


def _locate(lines: list[str], title: str) -> int | None:
    for n, line in enumerate(lines, 1):
        match = JS_CALL.match(line)
        if match and match[2] == title:
            return n
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _js_end(lines: list[str], start: int) -> int:
    """The last line of the test call opening on `start`, by indentation: the first later
    line at or left of its indent, when that line closes the call."""
    indent = _indent(lines[start - 1])
    for n in range(start + 1, len(lines) + 1):
        text = lines[n - 1]
        if text.strip() and _indent(text) <= indent:
            closes = _indent(text) == indent and text.lstrip().startswith(("}", ")"))
            return n if closes else n - 1
    return len(lines)


def js_touched(
    source: str, tests: list[tuple[str, int | None]], changed: set[int] | None
) -> list[bool]:
    """For each (title, start line), whether the diff changed that test.

    A test owns the lines of its own call, from its start to its closing bracket. A start
    line the runner did not report is found by the test's title.
    """
    if changed is None:
        return [True for _ in tests]
    lines = source.splitlines()
    spans: list[tuple[int, int] | None] = []
    for title, line in tests:
        start = line or _locate(lines, title)
        valid = start is not None and 0 < start <= len(lines)
        spans.append((start, _js_end(lines, start)) if valid and start else None)
    return _all_or_each(spans, _real(source, changed, JS_NOISE))
