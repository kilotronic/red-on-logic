"""The pluggable runner: any command that writes JUnit XML."""

from __future__ import annotations

import sys
from pathlib import Path

from conftest import Planted, verdicts

# A tiny "test runner" for a made-up language: each line of a .check file is
# `<python expression> == <expected>`, judged against code.py, written out as JUnit.
RUNNER = """
import sys, xml.sax.saxutils as su
junit, files = sys.argv[1], sys.argv[2:]
cases = []
for f in files:
    try:
        ns = {}
        exec(open("code.py").read(), ns)
    except Exception as e:
        cases.append((f, "load", "error", repr(e)))
        continue
    for i, line in enumerate(open(f).read().splitlines(), 1):
        try:
            ok = eval(line, ns)
        except NameError as e:
            cases.append((f, f"line{i}", "error", repr(e)))
            continue
        cases.append((f, f"line{i}", "pass" if ok else "failure", line))
out = ["<testsuite>"]
for f, name, kind, msg in cases:
    body = "" if kind == "pass" else f'<{kind} message={su.quoteattr(msg)}/>'
    out.append(f'<testcase classname={su.quoteattr(f)} name="{name}" file="{f}">{body}</testcase>')
out.append("</testsuite>")
open(junit, "w").write("\\n".join(out))
"""


def _setup(planted: Planted, tmp_path: Path) -> list[str]:
    runner = tmp_path / "runner.py"
    runner.write_text(RUNNER)
    planted.write("code.py", "def add(a, b):\n    return a - b\n")
    planted.write("checks/zero.check", "add(0, 0) == 0\n")
    planted.base()
    planted.write("code.py", "def add(a, b):\n    return a + b\n")
    return [
        "--runner",
        "command",
        "--command",
        f"{sys.executable} {runner} {{junit}} {{files}}",
        "--test-paths",
        "checks/*.check",
    ]


def test_a_real_check_is_proven(planted: Planted, tmp_path: Path) -> None:
    args = _setup(planted, tmp_path)
    planted.write("checks/add.check", "add(1, 2) == 3\n")
    planted.commit("fix")

    code, report, text = planted.run(*args)

    assert code == 0, text
    assert verdicts(report) == {"checks/add.check::line1": "proven"}


def test_a_vacuous_check_fails(planted: Planted, tmp_path: Path) -> None:
    args = _setup(planted, tmp_path)
    planted.write("checks/add.check", "add(5, 0) == 5\n")
    planted.commit("fix")

    code, report, _ = planted.run(*args)

    assert code == 1
    assert verdicts(report) == {"checks/add.check::line1": "vacuous"}


def test_a_junit_error_is_red_on_import(planted: Planted, tmp_path: Path) -> None:
    args = _setup(planted, tmp_path)
    planted.write(
        "code.py", "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
    )
    planted.write("checks/mul.check", "mul(2, 3) == 6\n")
    planted.commit("feat")

    code, report, _ = planted.run(*args)

    assert code == 1
    assert verdicts(report) == {"checks/mul.check::line1": "red-on-import"}


def test_a_command_that_writes_no_report_is_a_tool_error(planted: Planted, tmp_path: Path) -> None:
    _setup(planted, tmp_path)
    planted.write("checks/add.check", "add(1, 2) == 3\n")
    planted.commit("fix")

    code, _, _ = planted.run(
        "--runner", "command", "--command", "true", "--test-paths", "checks/*.check"
    )

    assert code == 2


def test_the_command_runner_needs_test_paths(planted: Planted) -> None:
    planted.write("a.txt", "a\n")
    planted.base()
    planted.write("a.txt", "b\n")
    planted.commit("x")

    code, _, _ = planted.run("--runner", "command", "--command", "true")

    assert code == 2
