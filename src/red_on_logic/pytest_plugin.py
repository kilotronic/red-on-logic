"""Loaded into the pytest run under test as `-p red_on_logic_pytest_plugin`.

Writes one JSON object per line to $RED_ON_LOGIC_OUT: each test phase's outcome, with the
exception's type and whether it is an assertion, and each file that failed to collect.
Imports nothing outside pytest and the standard library: it runs in the tested project's
interpreter. The facts travel in `user_properties`, so they survive pytest-xdist.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from typing import Any

import pytest

_root = ""
KEY = "red_on_logic"


def _write(record: dict[str, Any]) -> None:
    with open(os.environ["RED_ON_LOGIC_OUT"], "a", encoding="utf-8") as out:
        out.write(json.dumps(record) + "\n")


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0][:300] if lines else ""


def pytest_configure(config: pytest.Config) -> None:
    global _root
    _root = str(config.rootpath)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, Any, None]:
    del item
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    excinfo = call.excinfo
    if excinfo is not None:
        fact = {
            "type": excinfo.typename,
            "message": _first_line(str(excinfo.value)),
            "assertion": bool(
                excinfo.errisinstance(AssertionError) or excinfo.typename == "Failed"
            ),
        }
        report.user_properties.append((KEY, json.dumps(fact)))


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    exc = next((json.loads(str(v)) for k, v in report.user_properties if k == KEY), None)
    _write(
        {
            "root": _root,
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "exc": exc,
        }
    )


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if not report.failed:
        return
    text = str(report.longrepr)
    lines = [ln[1:].strip() for ln in text.splitlines() if ln.startswith("E ")]
    tail = text.strip().splitlines()
    _write(
        {
            "root": _root,
            "collect": report.nodeid,
            "message": lines[-1] if lines else (tail[-1] if tail else ""),
        }
    )
