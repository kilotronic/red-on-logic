"""The Action's step script, run as GitHub runs it: inputs in the environment."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import PYTEST, Planted, git

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "src" / "red_on_logic" / "action.sh"


def _step(planted: Planted, tmp_path: Path, **inputs: str) -> tuple[int, str, str]:
    summary = tmp_path / "summary.md"
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "PYTEST_"))},
        "GITHUB_ACTION_PATH": str(ROOT),
        "GITHUB_STEP_SUMMARY": str(summary),
        **inputs,
    }
    done = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=planted.root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return (
        done.returncode,
        done.stdout + done.stderr,
        summary.read_text() if summary.exists() else "",
    )


def _fix(planted: Planted) -> str:
    planted.write("calc.py", "def add(a, b):\n    return a - b\n")
    base = planted.base()
    planted.write("calc.py", "def add(a, b):\n    return a + b\n")
    planted.write(
        "tests/test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.commit("fix")
    return base


def test_the_step_proves_a_real_test(planted: Planted, tmp_path: Path) -> None:
    base = _fix(planted)

    code, output, summary = _step(planted, tmp_path, BASE=base, PYTEST_CMD=PYTEST, LABELS="[]")

    assert code == 0, output
    assert "red-on-logic: proven" in output
    assert "| tests/test_calc.py::test_add |" in summary


def test_the_step_reads_a_skip_label(planted: Planted, tmp_path: Path) -> None:
    base = _fix(planted)
    labels = json.dumps(["bug", "red-on-logic: not applicable (docs only)"])

    code, output, _ = _step(planted, tmp_path, BASE=base, LABELS=labels)

    assert code == 0, output
    assert "docs only" in output


def test_the_step_passes_test_paths_and_a_command(planted: Planted, tmp_path: Path) -> None:
    base = _fix(planted)
    git(planted.root, "rm", "-q", "tests/test_calc.py")
    planted.write("checks/a.check", "x\n")
    planted.commit("checks")

    code, output, _ = _step(
        planted,
        tmp_path,
        BASE=base,
        RUNNER="command",
        RUN_CMD="echo '<testsuite/>' > {junit}",
        TEST_PATHS="checks/*.check, other/*.x",
    )

    assert code == 1, output
    assert "did not run" in output
    assert "reported no tests" in output


def test_the_step_does_nothing_without_a_base(planted: Planted, tmp_path: Path) -> None:
    _fix(planted)

    code, output, _ = _step(planted, tmp_path, BASE="")

    assert code == 0
    assert "nothing to check" in output


def test_the_step_refuses_a_base_it_cannot_get(planted: Planted, tmp_path: Path) -> None:
    _fix(planted)

    code, output, _ = _step(planted, tmp_path, BASE="0" * 40)

    assert code == 2
    assert "fetch-depth: 0" in output


def test_a_merge_checkout_judges_against_its_first_parent(planted: Planted, tmp_path: Path) -> None:
    # The event's base is stale: main moved on with someone else's skip line.
    stale = _fix(planted)
    pr_head = git(planted.root, "rev-parse", "HEAD").strip()
    git(planted.root, "checkout", "-q", "main")
    planted.write("other.py", "x = 1\n")
    planted.commit("chore: other\n\nred-on-logic: not applicable (someone else's change)")
    git(planted.root, "merge", "-q", "--no-ff", "-m", "Merge", pr_head)
    git(planted.root, "checkout", "-q", "--detach", "HEAD")

    code, output, _ = _step(planted, tmp_path, BASE=stale, PR_HEAD=pr_head, PYTEST_CMD=PYTEST)

    assert code == 0, output
    assert "red-on-logic: proven" in output
    assert "someone else" not in output


def test_a_label_that_looks_like_an_option_is_only_a_label(
    planted: Planted, tmp_path: Path
) -> None:
    base = _fix(planted)

    code, output, _ = _step(
        planted, tmp_path, BASE=base, PYTEST_CMD=PYTEST, LABELS=json.dumps(["--summary=x"])
    )

    assert code == 0, output
    assert not (planted.root / "x").exists()
