"""What kind of failure a test had on the base.

    assertion  a wrong answer: an assertion or an expectation failed
    crash      the code under test raised: also a wrong answer (a crash a fix removes)
    shape      the test reached for something the base does not have: a missing module,
               name, attribute or argument. Red on import, not on logic.

A setup or collection error is never judged here: it is red on import by itself.
"""

from __future__ import annotations

import re

PY_SHAPE_TYPES = frozenset({"ImportError", "ModuleNotFoundError", "NameError", "UnboundLocalError"})
PY_SHAPE_MESSAGES = re.compile(
    "|".join(
        [
            r"^module '[^']+' has no attribute",
            r"^type object '[^']+' has no attribute",
            r"^'(?!NoneType')[^']+' object has no attribute",
            r"unexpected keyword argument",
            r"missing \d+ required (positional|keyword-only) argument",
            r"takes \d+ positional arguments? but \d+ (was|were) given",
            r"takes no arguments",
            r"^cannot import name",
        ]
    )
)
JS_ASSERTION = re.compile(r"^(AssertionError|JestAssertionError|Error: expect\(|Error: Snapshot )")
JS_SHAPE = re.compile(
    "|".join(
        [
            r"is not a function",
            r"is not a constructor",
            r"^ReferenceError: .* is not defined",
            r"does not provide an export named",
            r"Cannot find module",
            r"Cannot find package",
            r"ERR_MODULE_NOT_FOUND",
            r"Failed to (load|resolve import)",
            r"__vite_ssr_import_\d+__",
            r"__vi_import_\d+__",
        ]
    )
)


def python_kind(exc: str, message: str, *, assertion: bool) -> str:
    """`exc` is the exception's type name; `assertion` whether it is an AssertionError or
    pytest's own failure (pytest.fail, pytest.raises that saw nothing)."""
    if assertion:
        return "assertion"
    if exc in PY_SHAPE_TYPES:
        return "shape"
    if exc in ("AttributeError", "TypeError") and PY_SHAPE_MESSAGES.search(message):
        return "shape"
    return "crash"


def js_kind(message: str) -> str:
    """`message` is the failure's first line, `Type: text`, as vitest, jest and node print it."""
    first = message.strip().splitlines()[0] if message.strip() else ""
    if JS_ASSERTION.search(first):
        return "assertion"
    if JS_SHAPE.search(first):
        return "shape"
    return "crash"
