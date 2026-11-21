"""Skips, refusals and reporting, end to end."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import PYTEST, Planted, git

from red_on_logic.cli import main
from red_on_logic.skip import SkipError, find_skip


def _fix_with_test(planted: Planted, message: str = "fix") -> None:
    planted.write("calc.py", "def add(a, b):\n    return a - b\n")
    planted.base()
    planted.write("calc.py", "def add(a, b):\n    return a + b\n")
    planted.write(
        "tests/test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.commit(message)


def test_a_commit_trailer_skips_with_its_reason(planted: Planted) -> None:
    planted.write("calc.py", "x = 1\n")
    planted.base()
    planted.write("calc.py", "x = 1  # tidy\n")
    planted.commit(
        "refactor: tidy\n\nred-on-logic: not applicable (pure refactor, no behaviour change)"
    )

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 0
    assert report["result"] == "skipped"
    assert "pure refactor, no behaviour change" in text


def test_a_label_skips_with_its_reason(planted: Planted) -> None:
    planted.write("README.md", "a\n")
    planted.base()
    planted.write("README.md", "b\n")
    planted.commit("docs: b")

    code, _, text = planted.run("--label", "red-on-logic: not applicable (docs only)")

    assert code == 0
    assert "docs only" in text


def test_a_skip_without_a_reason_is_refused(planted: Planted) -> None:
    planted.write("README.md", "a\n")
    planted.base()
    planted.write("README.md", "b\n")
    planted.commit("docs: b\n\nred-on-logic: not applicable ()")

    code, _, text = planted.run()

    assert code == 1
    assert "needs a reason" in text


def test_no_changed_tests_fails_and_says_how_to_skip(planted: Planted) -> None:
    planted.write("calc.py", "x = 1\n")
    planted.base()
    planted.write("calc.py", "x = 2\n")
    planted.commit("fix")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 1
    assert report["result"] == "no-tests"
    assert "red-on-logic: not applicable (" in text


def test_a_test_only_change_says_no_code_changed(planted: Planted) -> None:
    planted.write("calc.py", "def add(a, b):\n    return a + b\n")
    planted.base()
    planted.write(
        "tests/test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.commit("test: add")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 1
    assert report["result"] == "not-proven"
    assert "changes no code" in text


def test_a_dirty_tree_is_refused_and_left_alone(planted: Planted) -> None:
    _fix_with_test(planted)
    planted.write("calc.py", "def add(a, b):\n    return 0\n")

    code, _, _ = planted.run("--pytest", PYTEST)

    assert code == 2
    assert "return 0" in (planted.root / "calc.py").read_text()


def test_the_tree_is_restored_when_the_runner_fails(planted: Planted) -> None:
    _fix_with_test(planted)
    before = planted.tree()

    code, _, _ = planted.run("--pytest", "false")

    assert code == 2
    assert planted.tree() == before
    assert git(planted.root, "status", "--porcelain", "--untracked-files=no") == ""


def test_the_markdown_summary_is_written(planted: Planted, tmp_path: Path) -> None:
    _fix_with_test(planted)
    summary = tmp_path / "summary.md"

    code, _, _ = planted.run("--pytest", PYTEST, "--summary", str(summary))

    assert code == 0
    text = summary.read_text()
    assert "| tests/test_calc.py::test_add |" in text
    assert "fails on the base" in text


def test_an_unknown_base_is_a_tool_error(planted: Planted) -> None:
    _fix_with_test(planted)

    code = main(["--repo", str(planted.root), "--base", "no-such-ref"])

    assert code == 2


@pytest.mark.parametrize(
    ("messages", "labels", "reason"),
    [
        (["fix\n\nred-on-logic: not applicable (docs)"], [], "docs"),
        (["fix\n\nRed-On-Logic: Not Applicable (a (nested) reason)"], [], "a (nested) reason"),
        ([], ["red-on-logic: not applicable (refactor)"], "refactor"),
        (["fix: mention red-on-logic: not applicable (x) inline"], [], None),
        (["fix"], ["bug"], None),
        (["fix\n\nred-on-logic: not applicable here, see above"], [], None),
        (["fix\n\n    red-on-logic: not applicable (indented prose)"], [], None),
    ],
)
def test_find_skip(messages: list[str], labels: list[str], reason: str | None) -> None:
    found = find_skip(messages, labels)
    assert (found.reason if found else None) == reason


def test_find_skip_refuses_an_empty_reason() -> None:
    with pytest.raises(SkipError, match="needs a reason"):
        find_skip([], ["red-on-logic: not applicable"])


def test_find_skip_refuses_the_placeholder() -> None:
    with pytest.raises(SkipError, match="needs a reason"):
        find_skip(["x\n\nred-on-logic: not applicable (<reason>)"], [])


def test_changed_test_files_with_no_changed_test_say_so(planted: Planted) -> None:
    planted.write("calc.py", "def add(a, b):\n    return a + b\n")
    planted.write(
        "tests/test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.base()
    planted.write(
        "tests/test_calc.py",
        "from calc import add\n\n\ndef test_add():\n    # why\n    assert add(1, 2) == 3\n",
    )
    planted.commit("docs")

    code, _, text = planted.run("--pytest", PYTEST)

    assert code == 1
    assert "no test in them changed" in text


def test_a_moved_head_is_not_reset(planted: Planted, monkeypatch: pytest.MonkeyPatch) -> None:
    import red_on_logic.cli as cli

    _fix_with_test(planted)
    real = cli._run_all  # pyright: ignore[reportPrivateUsage]
    calls: list[int] = []

    def run_all(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) == 2:
            git(planted.root, "checkout", "-q", "main")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "_run_all", run_all)
    main_before = git(planted.root, "rev-parse", "main")

    code, _, _ = planted.run("--pytest", PYTEST)

    assert code == 2
    assert git(planted.root, "rev-parse", "main") == main_before


def test_code_paths_swap_a_template(planted: Planted) -> None:
    planted.write("greet.txt", "hello {}\n")
    planted.write("greet.py", "def greet(n):\n    return open('greet.txt').read().format(n)\n")
    planted.base()
    planted.write("greet.txt", "hi {}\n")
    planted.write(
        "tests/test_greet.py",
        "from greet import greet\n\n\ndef test_hi():\n    assert greet('a') == 'hi a\\n'\n",
    )
    planted.commit("fix")

    vacuous, _, _ = planted.run("--pytest", PYTEST)
    proven, report, text = planted.run("--pytest", PYTEST, "--code-paths", "*.txt")

    assert vacuous == 1
    assert proven == 0, text
    assert report["result"] == "proven"
