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
TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "testdata", "testing"})
PY_NOISE = re.compile(r"^\s*(#.*)?$")
JS_NOISE = re.compile(r"^\s*(//.*|/\*.*|\*.*)?$")
JS_CALL = re.compile(r"""^\s*(?:test|it)(?:\.\w+)*\s*\(\s*(['"`])(.*?)\1""")


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Head-side line numbers each file's hunks touch, from `git diff -U0`.

    A hunk that only deletes lines marks the line it lands on, so a test that lost
    lines counts as changed.
    """
    out: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = None if target == "/dev/null" else out.setdefault(target[2:], set())
        elif current is not None and (match := HUNK.match(line)):
            start, count = int(match[1]), int(match[2] or 1)
            current.update(range(start, start + count) if count else {max(start, 1)})
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


def python_touched(source: str, keys: list[str], changed: set[int] | None) -> list[bool]:
    """For each test key (`test_a`, `TestC::test_d`), whether the diff changed it.

    None for `changed` means a new file: every test is new. A changed line outside every
    function and class (an import, a constant, a module-level helper) touches every test,
    since any of them may read it. Blank and comment-only lines touch nothing. A key the
    source does not define (a generated test) counts as touched.
    """
    if changed is None:
        return [True for _ in keys]
    real = _real(source, changed, PY_NOISE)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [True for _ in keys]
    spans = dict(_spans(tree.body, ""))
    inside = {n for s, e in spans.values() for n in range(s, e + 1)}
    classes = {
        n
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for n in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    }
    if real - inside - classes:
        return [True for _ in keys]
    out: list[bool] = []
    for key in keys:
        span = spans.get(key)
        out.append(span is None or any(span[0] <= n <= span[1] for n in real))
    return out


def _locate(lines: list[str], title: str) -> int | None:
    for n, line in enumerate(lines, 1):
        match = JS_CALL.match(line)
        if match and match[2] == title:
            return n
    return None


def js_touched(
    source: str, tests: list[tuple[str, int | None]], changed: set[int] | None
) -> list[bool]:
    """For each (title, start line), whether the diff changed that test.

    A test owns the lines from its start to the next test's start. A changed line before
    the first test (imports, helpers) touches every test; a start line the runner did not
    report is found by the test's title.
    """
    if changed is None:
        return [True for _ in tests]
    lines = source.splitlines()
    real = _real(source, changed, JS_NOISE)
    starts = [line or _locate(lines, title) for title, line in tests]
    known = sorted({s for s in starts if s})
    if not known or any(n < known[0] for n in real):
        return [True for _ in tests]
    out: list[bool] = []
    for start in starts:
        if start is None:
            out.append(True)
            continue
        end = next((s - 1 for s in known if s > start), len(lines))
        out.append(any(start <= n <= end for n in real))
    return out
