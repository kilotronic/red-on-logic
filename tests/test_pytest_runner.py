"""pytest on planted examples: a real test, a vacuous one and one that is red only on import."""

from __future__ import annotations

from conftest import PYTEST, Planted, verdicts

CALC_BASE = "def add(a, b):\n    return a - b\n"
CALC_FIXED = "def add(a, b):\n    return a + b\n"
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
    assert "no new or changed tests" in text


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
