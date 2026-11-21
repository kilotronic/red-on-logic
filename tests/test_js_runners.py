"""vitest, jest and node:test on planted examples: real, vacuous and red only on import."""

from __future__ import annotations

import pytest
from conftest import Planted, verdicts

ESM_BASE = "export function add(a, b) {\n  return a - b;\n}\n"
ESM_FIXED = "export function add(a, b) {\n  return a + b;\n}\n"
CJS_BASE = "exports.add = (a, b) => a - b;\n"
CJS_FIXED = "exports.add = (a, b) => a + b;\n"

VITEST_HEAD = 'import { test, expect } from "vitest";\nimport { add } from "./calc.js";\n\n'
JEST_HEAD = 'const { add } = require("./calc");\n\n'
NODE_HEAD = (
    'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
    'import { add } from "./calc.js";\n\n'
)

RUNNERS = {
    # runner: (package.json, base code, fixed code, code file, test header, assert, new-name import)
    "vitest": (
        '{"type": "module", "devDependencies": {"vitest": "*"}}\n',
        ESM_BASE,
        ESM_FIXED,
        "calc.js",
        VITEST_HEAD,
        "expect({x}).toBe({y});",
        'import { test, expect } from "vitest";\nimport { mul } from "./calc.js";\n\n'
        'test("mul", () => {\n  expect(mul(2, 3)).toBe(6);\n});\n',
    ),
    "jest": (
        '{"devDependencies": {"jest": "*"}}\n',
        CJS_BASE,
        CJS_FIXED,
        "calc.js",
        JEST_HEAD,
        "expect({x}).toBe({y});",
        'const { mul } = require("./mul");\n\n'
        'test("mul", () => {\n  expect(mul(2, 3)).toBe(6);\n});\n',
    ),
    "node": (
        '{"type": "module"}\n',
        ESM_BASE,
        ESM_FIXED,
        "calc.js",
        NODE_HEAD,
        "assert.equal({x}, {y});",
        'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
        'import { mul } from "./calc.js";\n\n'
        'test("mul", () => {\n  assert.equal(mul(2, 3), 6);\n});\n',
    ),
}


IMPORT_DETAIL = {
    "vitest": "is not a function",
    "jest": "Cannot find module './mul'",
    "node": "does not provide an export named 'mul'",
}


def _case(title: str, assertion: str, x: str, y: str) -> str:
    return f'test("{title}", () => {{\n  {assertion.format(x=x, y=y)}\n}});\n'


def _base(planted: Planted, runner: str) -> tuple[str, str, str, str]:
    package, base, fixed, code, head, assertion, _ = RUNNERS[runner]
    planted.write("package.json", package)
    planted.write(code, base)
    existing = head + _case("zero", assertion, "add(0, 0)", "0")
    planted.write("calc.test.js", existing)
    planted.link_node_modules()
    planted.base()
    return fixed, code, existing, assertion


@pytest.mark.parametrize("runner", sorted(RUNNERS))
def test_a_real_test_is_proven(planted: Planted, runner: str) -> None:
    fixed, code, existing, assertion = _base(planted, runner)
    planted.write(code, fixed)
    planted.write("calc.test.js", existing + "\n" + _case("adds", assertion, "add(1, 2)", "3"))
    planted.commit("fix: add adds")
    before = planted.tree()

    exit_code, report, text = planted.run()

    assert exit_code == 0, text
    assert report["result"] == "proven"
    assert list(verdicts(report).values()) == ["proven"]
    assert report["tests"][0]["runner"] == runner
    assert planted.tree() == before


@pytest.mark.parametrize("runner", sorted(RUNNERS))
def test_a_vacuous_test_fails_the_check(planted: Planted, runner: str) -> None:
    fixed, code, existing, assertion = _base(planted, runner)
    planted.write(code, fixed)
    planted.write("calc.test.js", existing + "\n" + _case("adds zero", assertion, "add(5, 0)", "5"))
    planted.commit("fix: add adds")

    exit_code, report, text = planted.run()

    assert exit_code == 1, text
    assert list(verdicts(report).values()) == ["vacuous"]


@pytest.mark.parametrize("runner", sorted(RUNNERS))
def test_a_test_red_only_on_import_is_not_proof(planted: Planted, runner: str) -> None:
    _, code, _, _ = _base(planted, runner)
    new_test = RUNNERS[runner][6]
    if runner == "jest":
        planted.write("mul.js", "exports.mul = (a, b) => a * b;\n")
    else:
        planted.write(
            code, RUNNERS[runner][1] + "export function mul(a, b) {\n  return a * b;\n}\n"
        )
    planted.write("mul.test.js", new_test)
    planted.commit("feat: mul")

    exit_code, report, text = planted.run()

    assert exit_code == 1, text
    assert list(verdicts(report).values()) == ["red-on-import"], text
    assert IMPORT_DETAIL[runner] in text


def test_a_node_test_file_runs_under_node_beside_vitest(planted: Planted) -> None:
    planted.write("package.json", RUNNERS["vitest"][0])
    planted.write("calc.js", ESM_BASE)
    planted.write(
        "calc.test.js", NODE_HEAD + _case("zero", "assert.equal({x}, {y});", "add(0, 0)", "0")
    )
    planted.link_node_modules()
    planted.base()
    planted.write("calc.js", ESM_FIXED)
    planted.write(
        "calc.test.js", NODE_HEAD + _case("adds", "assert.equal({x}, {y});", "add(1, 2)", "3")
    )
    planted.commit("fix")

    exit_code, report, text = planted.run()

    assert exit_code == 0, text
    assert report["tests"][0]["runner"] == "node"


def test_only_the_changed_js_test_is_judged(planted: Planted) -> None:
    fixed, code, existing, assertion = _base(planted, "vitest")
    planted.write(code, fixed)
    planted.write(
        "calc.test.js",
        existing
        + "\n"
        + _case("adds", assertion, "add(1, 2)", "3")
        + "\n"
        + _case("zero again", assertion, "add(0, 0)", "0"),
    )
    planted.commit("fix")
    planted.write(
        "calc.test.js",
        existing + "\n" + _case("zero again", assertion, "add(0, 0)", "0"),
    )
    # Back to one new test that is vacuous; "zero" must stay unjudged.
    planted.commit("fix: drop adds")

    exit_code, report, _ = planted.run()

    judged = verdicts(report)
    assert exit_code == 1
    assert judged == {"calc.test.js > zero again": "vacuous"}


def test_a_js_test_file_with_no_runner_is_reported(planted: Planted) -> None:
    planted.write("package.json", "{}\n")
    planted.write("calc.js", CJS_BASE)
    planted.base()
    planted.write("calc.js", CJS_FIXED)
    planted.write("calc.test.js", JEST_HEAD + 'test("adds", () => {});\n')
    planted.commit("fix")

    exit_code, _, text = planted.run()

    assert exit_code == 1
    assert "No test runner found for calc.test.js" in text
    assert "could be run" in text
