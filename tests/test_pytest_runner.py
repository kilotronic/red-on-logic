"""pytest on planted examples: a real test, a vacuous one and one that is red only on import."""

from __future__ import annotations

from conftest import PYTEST, Planted, verdicts

CALC_BASE = "def add(a, b):\n    return a - b\n"
CALC_FIXED = "def add(a, b):\n    return a + b\n"
HELPER = (
    "from calc import add\n\n\ndef want():\n    return {w}\n\n\n"
    "def test_add():\n    assert add(1, 2) == want()\n"
)
EXISTING = "from calc import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n"


def _base(planted: Planted) -> None:
    planted.write("calc.py", CALC_BASE)
    planted.write("tests/test_calc.py", EXISTING)
    planted.base()


def test_a_real_test_is_proven(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py",
        EXISTING + "\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.commit("fix: add adds")
    before = planted.tree()

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 0, text
    assert report["result"] == "proven"
    assert verdicts(report) == {"tests/test_calc.py::test_add": "proven"}
    assert "test_add" in text
    assert planted.tree() == before


def test_a_vacuous_test_fails_the_check(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py",
        EXISTING + "\n\ndef test_add_zero():\n    assert add(5, 0) == 5\n",
    )
    planted.commit("fix: add adds")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 1
    assert report["result"] == "not-proven"
    assert verdicts(report) == {"tests/test_calc.py::test_add_zero": "vacuous"}
    assert "passes on the base" in text


def test_a_test_red_only_on_import_is_not_proof(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_BASE + "\n\ndef mul(a, b):\n    return a * b\n")
    planted.write(
        "tests/test_mul.py",
        "from calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
    )
    planted.commit("feat: mul")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report) == {"tests/test_mul.py::test_mul": "red-on-import"}
    assert "ImportError" in text


def test_a_missing_attribute_is_red_on_import(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_BASE + "\n\ndef mul(a, b):\n    return a * b\n")
    planted.write(
        "tests/test_mul.py", "import calc\n\n\ndef test_mul():\n    assert calc.mul(2, 3) == 6\n"
    )
    planted.commit("feat: mul")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report) == {"tests/test_mul.py::test_mul": "red-on-import"}


def test_a_crash_on_the_base_is_proof(planted: Planted) -> None:
    planted.write("calc.py", "def mean(xs):\n    return sum(xs) / len(xs)\n")
    planted.write(
        "tests/test_calc.py",
        "from calc import mean\n\n\ndef test_one():\n    assert mean([2]) == 2\n",
    )
    planted.base()
    planted.write("calc.py", "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n")
    planted.write(
        "tests/test_calc.py",
        "from calc import mean\n\n\ndef test_one():\n    assert mean([2]) == 2\n\n\n"
        "def test_empty():\n    assert mean([]) == 0\n",
    )
    planted.commit("fix: mean of nothing")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 0, text
    assert verdicts(report) == {"tests/test_calc.py::test_empty": "proven"}
    assert "ZeroDivisionError" in text


def test_a_test_that_fails_on_head_too_proves_nothing(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_always():\n    assert False, 'always'\n"
    )
    planted.commit("fix: add adds")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report) == {"tests/test_calc.py::test_always": "broken-on-head"}


def test_untouched_tests_in_a_changed_file_are_not_judged(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    planted.commit("fix")

    _, report, _ = planted.run("--pytest", PYTEST)

    by_id = {t["id"]: t for t in report["tests"]}
    assert by_id["tests/test_calc.py::test_zero"]["judged"] is False
    assert by_id["tests/test_calc.py::test_add"]["judged"] is True


def test_a_comment_only_change_judges_nothing(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py",
        EXISTING.replace("    assert add(0, 0) == 0\n", "    # zero\n    assert add(0, 0) == 0\n"),
    )
    planted.commit("docs: a comment")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 1
    assert report["result"] == "no-tests"
    assert "no test in them changed" in text


def test_a_change_outside_any_test_judges_the_whole_file(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py",
        "from calc import add\n\nWANT = 3\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n\n\n"
        "def test_sum():\n    assert add(1, 2) == WANT\n",
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {
        "tests/test_calc.py::test_zero": "vacuous",
        "tests/test_calc.py::test_sum": "proven",
    }


def test_class_methods_and_parameters_are_matched(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_cls.py",
        "import pytest\nfrom calc import add\n\n\nclass TestAdd:\n"
        "    @pytest.mark.parametrize('b', [1, 0])\n"
        "    def test_one(self, b):\n        assert add(2, b) == 2 + b\n",
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {
        "tests/test_cls.py::TestAdd::test_one[1]": "proven",
        "tests/test_cls.py::TestAdd::test_one[0]": "vacuous",
    }


def test_same_size_swap_does_not_reuse_stale_bytecode(planted: Planted) -> None:
    # `a - b` and `a + b` are the same size, and the swap lands in the same second as the
    # head run: a cached .pyc would run the head's code on the base.
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {"tests/test_calc.py::test_add": "proven"}


def test_a_new_code_file_is_absent_on_the_base_and_a_deleted_one_is_back(planted: Planted) -> None:
    planted.write("calc.py", CALC_BASE)
    planted.write("old.py", "VALUE = 1\n")
    planted.write("tests/test_calc.py", EXISTING)
    planted.base()
    planted.delete("old.py")
    planted.write(
        "calc.py", "from helpers import plus\n\n\ndef add(a, b):\n    return plus(a, b)\n"
    )
    planted.write("helpers.py", "def plus(a, b):\n    return a + b\n")
    planted.write(
        "tests/test_calc.py",
        EXISTING
        + "\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\n"
        + "def test_old_gone():\n    import importlib.util\n\n"
        + "    assert importlib.util.find_spec('old') is None\n",
    )
    planted.commit("refactor")
    before = planted.tree()

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {
        "tests/test_calc.py::test_add": "proven",
        "tests/test_calc.py::test_old_gone": "proven",
    }
    assert planted.tree() == before


def test_test_side_helpers_keep_the_head_version(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/conftest.py", "import pytest\n\n\n@pytest.fixture\ndef three():\n    return 3\n"
    )
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_add(three):\n    assert add(1, 2) == three\n"
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {"tests/test_calc.py::test_add": "proven"}


def test_a_fixture_error_on_the_base_is_not_proof(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_BASE + "\n\nclass Box:\n    pass\n")
    planted.write(
        "tests/test_box.py",
        "import pytest\nimport calc\n\n\n@pytest.fixture\ndef box():\n    return calc.Box()\n\n\n"
        "def test_box(box):\n    assert box is not None\n",
    )
    planted.commit("feat: box")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report) == {"tests/test_box.py::test_box": "red-on-import"}


def test_a_new_data_file_stays_for_the_base_run(planted: Planted) -> None:
    # Review finding: removing an added data file made the base fail with a crash.
    _base(planted)
    planted.write("data/want.json", "3\n")
    planted.write(
        "tests/test_data.py",
        "import json\nfrom calc import add\n\n\n"
        "def test_data():\n    assert json.load(open('data/want.json')) == 3\n",
    )
    planted.commit("test: data")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report) == {"tests/test_data.py::test_data": "vacuous"}


def test_config_files_keep_the_head_version(planted: Planted) -> None:
    # Review finding: base pyproject without the new marker made the base fail on setup.
    _base(planted)
    planted.write(
        "pyproject.toml",
        '[tool.pytest.ini_options]\nmarkers = ["slow"]\naddopts = "--strict-markers"\n',
    )
    planted.write(
        "tests/test_calc.py",
        "import pytest\n"
        + EXISTING
        + "\n\n@pytest.mark.slow\ndef test_marked():\n    assert add(0, 0) == 0\n",
    )
    planted.commit("test: marked")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report)["tests/test_calc.py::test_marked"] == "vacuous"


def test_a_process_that_dies_mid_test_is_not_a_pass_on_head(planted: Planted) -> None:
    _base(planted)
    planted.write(
        "calc.py",
        "import os\n\n\ndef add(a, b):\n    if a == 1:\n        os._exit(0)\n    return a + b\n",
    )
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    planted.commit("break")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert report["result"] != "proven"


def test_a_changed_helper_function_judges_the_whole_file(planted: Planted) -> None:
    planted.write("calc.py", CALC_BASE)
    planted.write(
        "tests/test_calc.py",
        HELPER.format(w=-1),
    )
    planted.base()
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py",
        HELPER.format(w=3),
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {"tests/test_calc.py::test_add": "proven"}


def test_a_changed_class_attribute_judges_the_class(planted: Planted) -> None:
    planted.write("calc.py", CALC_BASE)
    body = (
        "from calc import add\n\n\nclass TestAdd:\n    want = {w}\n\n"
        "    def test_add(self):\n        assert add(1, 2) == self.want\n"
    )
    planted.write("tests/test_calc.py", body.format(w=-1))
    planted.base()
    planted.write("calc.py", CALC_FIXED)
    planted.write("tests/test_calc.py", body.format(w=3))
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {"tests/test_calc.py::TestAdd::test_add": "proven"}


def test_test_files_with_spaces_and_accents_are_judged(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_café sum.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 0
    assert verdicts(report) == {
        "tests/test_café sum.py::test_add": "proven",
        "tests/test_calc.py::test_add": "proven",
    }


def test_an_untracked_file_at_a_deleted_path_is_refused(planted: Planted) -> None:
    planted.write("calc.py", CALC_BASE)
    planted.write("settings.py", "SECRET = 'base'\n")
    planted.write("tests/test_calc.py", EXISTING)
    planted.base()
    from conftest import git

    git(planted.root, "rm", "-q", "--cached", "settings.py")
    planted.write(".gitignore", "node_modules\n__pycache__/\n.pytest_cache/\nsettings.py\n")
    planted.write("settings.py", "SECRET = 'mine'\n")
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    planted.commit("stop tracking settings")

    code, _, _ = planted.run("--pytest", PYTEST)

    assert code == 2
    assert (planted.root / "settings.py").read_text() == "SECRET = 'mine'\n"


def test_a_pytest_internal_failure_is_not_proof(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED)
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\nasync def test_async():\n    assert add(1, 2) == 3\n"
    )
    planted.commit("fix")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report)["tests/test_calc.py::test_async"] != "proven"


def test_a_conftest_that_fails_to_load_on_the_base_is_red_on_import(planted: Planted) -> None:
    # Pilot finding: a shared helper importing a branch-only name stopped the base run.
    _base(planted)
    planted.write("calc.py", CALC_FIXED + "\n\nNEW = 1\n")
    planted.write("tests/conftest.py", "from calc import NEW  # noqa: F401\n")
    planted.write(
        "tests/test_calc.py", EXISTING + "\n\ndef test_new():\n    assert add(1, 1) == 2\n"
    )
    planted.commit("feat: new")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 1, text
    assert verdicts(report) == {"tests/test_calc.py::test_new": "red-on-import"}
    assert "conftest" in text


def test_a_cli_rejecting_a_new_option_is_red_on_import_by_pattern(planted: Planted) -> None:
    # Pilot finding: an old command line refusing a new flag read as a wrong answer. The
    # project names its command line's words for it.
    planted.write(
        "cli.py",
        "import argparse\n\n\ndef run(argv):\n"
        "    p = argparse.ArgumentParser(exit_on_error=False)\n"
        "    try:\n        p.parse_args(argv)\n    except argparse.ArgumentError as e:\n"
        "        return str(e)\n    return 'ok'\n",
    )
    planted.base()
    planted.write(
        "cli.py",
        "import argparse\n\n\ndef run(argv):\n"
        "    p = argparse.ArgumentParser(exit_on_error=False)\n"
        "    p.add_argument('--noop', action='store_true')\n"
        "    try:\n        p.parse_args(argv)\n    except argparse.ArgumentError as e:\n"
        "        return str(e)\n    return 'ok'\n",
    )
    planted.write(
        "tests/test_cli.py",
        "from cli import run\n\n\ndef test_noop():\n    out = run(['--noop'])\n"
        "    assert out == 'ok', out\n",
    )
    planted.commit("feat: --noop")

    proven, _, _ = planted.run("--pytest", PYTEST)
    code, report, _ = planted.run("--pytest", PYTEST, "--import-pattern", "^unrecognized arguments")

    assert proven == 0
    assert code == 1
    assert verdicts(report) == {"tests/test_cli.py::test_noop": "red-on-import"}


SERVICE = "\n\ndef call(name):\n    return 'ok' if name in KNOWN else f'unknown service: {name}'\n"


def test_a_repo_pattern_marks_its_own_missing_names(planted: Planted) -> None:
    planted.write(
        "svc.py",
        "KNOWN = {'a'}\n" + SERVICE,
    )
    planted.base()
    planted.write(
        "svc.py",
        "KNOWN = {'a', 'b'}\n" + SERVICE,
    )
    planted.write(
        "tests/test_svc.py",
        "from svc import call\n\n\ndef test_b():\n    out = call('b')\n"
        "    assert out == 'ok', out\n",
    )
    planted.commit("feat: b")

    proven, _, _ = planted.run("--pytest", PYTEST)
    code, report, _ = planted.run("--pytest", PYTEST, "--import-pattern", "unknown service")

    assert proven == 0
    assert code == 1
    assert verdicts(report) == {"tests/test_svc.py::test_b": "red-on-import"}


def test_a_conftest_in_one_folder_does_not_sink_the_others(planted: Planted) -> None:
    _base(planted)
    planted.write("calc.py", CALC_FIXED + "\n\nNEW = 1\n")
    planted.write("tests/a/conftest.py", "from calc import NEW  # noqa: F401\n")
    planted.write("tests/a/test_a.py", "def test_new():\n    assert True\n")
    planted.write(
        "tests/b/test_b.py",
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    planted.commit("feat")

    code, report, text = planted.run("--pytest", PYTEST)

    assert code == 0, text
    assert verdicts(report) == {
        "tests/a/test_a.py::test_new": "red-on-import",
        "tests/b/test_b.py::test_add": "proven",
    }


def test_a_conftest_that_fails_on_head_too_is_broken_on_head(planted: Planted) -> None:
    _base(planted)
    planted.write("tests/conftest.py", "import no_such_module  # noqa: F401\n")
    planted.write("tests/test_calc.py", EXISTING + "\n\ndef test_new():\n    assert True\n")
    planted.commit("broken")

    code, report, _ = planted.run("--pytest", PYTEST)

    assert code == 1
    assert verdicts(report) == {"tests/test_calc.py": "broken-on-head"}


def test_an_invalid_import_pattern_stops_before_any_run(planted: Planted) -> None:
    _base(planted)
    planted.write("tests/test_calc.py", EXISTING + "\n\ndef test_new():\n    assert True\n")
    planted.commit("x")

    code, _, _ = planted.run("--pytest", "false", "--import-pattern", "(unclosed")

    assert code == 2
