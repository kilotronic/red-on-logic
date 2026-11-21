"""The pure parts: diff parsing, test selection, touched tests and failure kinds."""

from __future__ import annotations

import pytest

from red_on_logic.classify import js_kind, python_kind
from red_on_logic.select import (
    changed_lines,
    is_test_file,
    is_test_side,
    js_touched,
    python_touched,
)

DIFF = """diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -3,0 +4,2 @@ def x():
+    one
+    two
@@ -9 +11 @@
-old
+new
@@ -20,2 +22,0 @@
-gone
-gone
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,3 @@
+a
+b
+c
"""


def test_changed_lines() -> None:
    assert changed_lines(DIFF) == {"tests/test_a.py": {4, 5, 11, 22}, "new.py": {1, 2, 3}}


@pytest.mark.parametrize(
    ("path", "want"),
    [
        ("tests/test_a.py", True),
        ("pkg/a_test.py", True),
        ("tests/conftest.py", False),
        ("tests/helpers.py", False),
        ("src/test_utils_module.txt", False),
        ("src/a.test.ts", True),
        ("src/a.spec.jsx", True),
        ("src/__tests__/a.js", True),
        ("src/a-test.mjs", True),
        ("src/test-a.cjs", True),
        ("src/a.ts", False),
        ("src/attest.py", False),
    ],
)
def test_is_test_file(path: str, want: bool) -> None:
    assert is_test_file(path, ()) is want


def test_extra_test_paths() -> None:
    assert is_test_file("checks/a.check", ("checks/*.check",))
    assert is_test_side("checks/a.check", ("checks/*.check",))


@pytest.mark.parametrize(
    ("path", "want"),
    [
        ("tests/helpers.py", True),
        ("tests/data/golden.json", True),
        ("pkg/conftest.py", True),
        ("src/__tests__/fixture.js", True),
        ("test/helper.js", True),
        ("src/calc.py", False),
        ("package.json", False),
        ("contest/a.py", False),
    ],
)
def test_is_test_side(path: str, want: bool) -> None:
    assert is_test_side(path, ()) is want


PY_SOURCE = """import pytest

HELPER = 1


def test_a():
    assert 1


@pytest.mark.x
def test_b():
    # a comment
    assert 2


class TestC:
    def test_d(self):
        assert 3
"""


@pytest.mark.parametrize(
    ("changed", "touched"),
    [
        ({7}, {"test_a"}),
        ({10}, {"test_b"}),
        ({12}, set[str]()),  # a comment only
        ({18}, {"TestC::test_d"}),
        ({3}, {"test_a", "test_b", "TestC::test_d"}),  # outside any test
        ({4}, set[str]()),  # a blank line
        (None, {"test_a", "test_b", "TestC::test_d"}),  # a new file
    ],
)
def test_python_touched(changed: set[int] | None, touched: set[str]) -> None:
    keys = ["test_a", "test_b", "TestC::test_d"]
    got = python_touched(PY_SOURCE, keys, changed)
    assert {k for k, t in zip(keys, got, strict=True) if t} == touched


JS_SOURCE = """import { test } from "vitest";

test("one", () => {
  expect(1).toBe(1);
});

describe("group", () => {
  it("two", () => {
    // note
    expect(2).toBe(2);
  });
});
"""


@pytest.mark.parametrize(
    ("changed", "touched"),
    [
        ({4}, {"one"}),
        ({10}, {"two"}),
        ({9}, set[str]()),
        ({1}, {"one", "two"}),
        (None, {"one", "two"}),
    ],
)
def test_js_touched(changed: set[int] | None, touched: set[str]) -> None:
    tests: list[tuple[str, int | None]] = [("one", 3), ("two", 8)]
    got = js_touched(JS_SOURCE, tests, changed)
    assert {t for (t, _), hit in zip(tests, got, strict=True) if hit} == touched


def test_js_touched_finds_a_title_without_a_line() -> None:
    assert js_touched(JS_SOURCE, [("one", None), ("two", None)], {10}) == [False, True]


@pytest.mark.parametrize(
    ("exc", "message", "want"),
    [
        ("AssertionError", "assert 1 == 2", "assertion"),
        ("Failed", "DID NOT RAISE ValueError", "assertion"),
        ("ZeroDivisionError", "division by zero", "crash"),
        ("AttributeError", "'NoneType' object has no attribute 'x'", "crash"),
        ("ImportError", "cannot import name 'x' from 'y'", "shape"),
        ("ModuleNotFoundError", "No module named 'x'", "shape"),
        ("NameError", "name 'x' is not defined", "shape"),
        ("AttributeError", "module 'calc' has no attribute 'mul'", "shape"),
        ("AttributeError", "type object 'Box' has no attribute 'make'", "shape"),
        ("AttributeError", "'Box' object has no attribute 'size'", "shape"),
        ("TypeError", "add() got an unexpected keyword argument 'c'", "shape"),
        ("TypeError", "add() missing 1 required positional argument: 'b'", "shape"),
        ("TypeError", "add() takes 2 positional arguments but 3 were given", "shape"),
        ("TypeError", "unsupported operand type(s) for +: 'int' and 'str'", "crash"),
    ],
)
def test_python_kind(exc: str, message: str, want: str) -> None:
    assert python_kind(exc, message, assertion=exc in ("AssertionError", "Failed")) == want


@pytest.mark.parametrize(
    ("message", "want"),
    [
        ("AssertionError: expected -1 to be 3 // Object.is equality", "assertion"),
        ("Error: expect(received).toBe(expected) // Object.is equality", "assertion"),
        ("AssertionError [ERR_ASSERTION]: Expected values to be strictly equal", "assertion"),
        ("TypeError: Cannot read properties of null (reading 'x')", "crash"),
        ("TypeError: (0 , __vite_ssr_import_1__.missing) is not a function", "shape"),
        ("TypeError: missing is not a function", "shape"),
        ("TypeError: Box is not a constructor", "shape"),
        ("ReferenceError: mul is not defined", "shape"),
        (
            "SyntaxError: The requested module './a.js' does not provide an export named 'x'",
            "shape",
        ),
        ("Error: Cannot find module './nope'", "shape"),
        ("RangeError: Invalid array length", "crash"),
    ],
)
def test_js_kind(message: str, want: str) -> None:
    assert js_kind(message) == want
