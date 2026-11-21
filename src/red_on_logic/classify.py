"""What kind of failure a test had on the base.

    assertion  a wrong answer: an assertion or an expectation failed
    crash      the code under test raised: also a wrong answer (a crash a fix removes)
    shape      the test reached for something the base does not have: a missing module,
               name, attribute or argument; or the run said nothing about the code (a
               timeout, an unsupported test). Red on import, not on logic.

A setup or collection error is never judged here: it is red on import by itself.
"""

from __future__ import annotations

import re

PY_SHAPE_TYPES = frozenset({"ImportError", "ModuleNotFoundError", "NameError", "UnboundLocalError"})
PY_SHAPE_MESSAGES = re.compile(
    "|".join(
        [
            r"^module '[^']+' has no attribute",
            r"^<module .*> (has no|does not have the) attribute",
            r"Mock object has no attribute",
            r"^type object '[^']+' has no attribute",
            r"^'(?!NoneType')[^']+' object has no attribute",
            r"unexpected keyword argument",
            r"missing \d+ required (positional|keyword-only) argument",
            r"takes (from \d+ to )?\d+ positional arguments? but \d+ (was|were) given",
            r"takes (at most|at least|exactly) \d+ arguments?",
            r"got multiple values for argument",
            r"positional-only arguments passed as keyword",
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
            r"is not defined on the object",
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


# pytest's own failures that say nothing about the code under test: an unsupported test
# shape (an async test with no plugin) or a plugin's timeout.
PY_NOT_LOGIC = re.compile(r"not natively supported|^Timeout >")
# Each runner's own words for a test that ran out of time; never an assertion's text.
JS_TIMEOUT = re.compile(
    r"^(Error: )?(Test timed out in \d+ ?ms|test timed out after \d+ ?ms)"
    r"|Exceeded timeout of \d+ ?ms for a (test|hook)"
)


# A command line that rejects a word the branch added (argparse's words), in whatever
# failure carries it, an assertion's message included: the old code lacks that name.
SHAPE_ANYWHERE = re.compile(r"unrecognized arguments:|invalid choice:")


def python_kind(exc: str, message: str, *, assertion: bool) -> str:
    """`exc` is the exception's type name; `assertion` whether it is an AssertionError or
    pytest's own failure (pytest.fail, pytest.raises that saw nothing)."""
    if SHAPE_ANYWHERE.search(message):
        return "shape"
    if exc == "Failed" and PY_NOT_LOGIC.search(message):
        return "shape"
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
    if SHAPE_ANYWHERE.search(first):
        return "shape"
    if JS_ASSERTION.search(first):
        return "assertion"
    if JS_TIMEOUT.search(first):
        return "shape"
    if JS_SHAPE.search(first):
        return "shape"
    return "crash"
