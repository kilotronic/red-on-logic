"""Run a group of test files under one runner and read back each test's outcome."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from red_on_logic.classify import js_kind, python_kind

RUNNERS = ("pytest", "vitest", "jest", "node", "command")
JS_RUNNERS = ("vitest", "jest", "node")
HERE = Path(__file__).parent
NODE_TEST_IMPORT = re.compile(r"""(?:from\s*|require\(\s*|import\(\s*)['"]node:test['"]""")
PY_CONFIGS = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")


class ToolError(Exception):
    """The check could not run: distinct from any verdict."""


@dataclass(frozen=True)
class Outcome:
    """One test's result on one run. `file_level` marks a file that failed to load."""

    file: str
    id: str
    status: str  # passed, failed, error, skipped
    kind: str = ""  # for failed: assertion or crash
    message: str = ""
    key: str = ""  # pytest: the test's name within the file, `TestC::test_d`
    title: str = ""  # js: the test's own title
    line: int | None = None
    file_level: bool = False


@dataclass(frozen=True)
class Group:
    runner: str
    cwd: Path
    files: tuple[str, ...]  # relative to the repository root


@dataclass(frozen=True)
class Commands:
    pytest: str | None = None
    vitest: str = "npx --no-install vitest run"
    jest: str = "npx --no-install jest"
    node: str = "node"
    command: str | None = None


def _rel(path: str | Path, root: Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _package(start: Path, root: Path) -> tuple[Path, dict[str, Any]] | None:
    d = start
    while True:
        pkg = d / "package.json"
        if pkg.is_file():
            try:
                data: object = json.loads(pkg.read_text())
            except (OSError, ValueError):
                data = {}
            return d, _dict(data)
        if d == root or d.parent == d:
            return None
        d = d.parent


def detect(rel: str, root: Path) -> tuple[str, Path] | None:
    """The runner and working directory for one test file, or None when there is none."""
    path = root / rel
    if rel.endswith(".py"):
        d = path.parent
        while d != root and not any((d / c).is_file() for c in PY_CONFIGS):
            d = d.parent
        return "pytest", d
    found = _package(path.parent, root)
    cwd = found[0] if found else root
    try:
        text = path.read_text()
    except OSError:
        text = ""
    if NODE_TEST_IMPORT.search(text):
        return "node", cwd
    if not found:
        return None
    data = found[1]
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps.update(_dict(data.get(key)))
    for runner in ("vitest", "jest"):
        if runner in deps:
            return runner, cwd
    test_script = str(_dict(data.get("scripts")).get("test", ""))
    for runner in ("vitest", "jest"):
        if runner in test_script:
            return runner, cwd
    if "node --test" in test_script:
        return "node", cwd
    return None


def _env(scratch: Path) -> dict[str, str]:
    env = dict(os.environ)
    # A fresh bytecode cache per run: the base's files land in the same second and size
    # as the head's, and a cached .pyc would run the head's code on the base.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(scratch / "pycache")
    env["CI"] = env.get("CI", "true")  # no watch mode, no colours
    env["FORCE_COLOR"] = "0"
    env["NO_COLOR"] = "1"
    return env


def _run(argv: list[str] | str, cwd: Path, env: dict[str, str], *, shell: bool = False) -> str:
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            shell=shell,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except OSError as e:
        raise ToolError(f"could not start {argv!r}: {e}") from e
    return (done.stdout + done.stderr)[-4000:]


def _no_report(runner: str, output: str) -> ToolError:
    return ToolError(f"{runner} wrote no results. Its output ended:\n{output}")


def default_pytest(root: Path, cwd: Path) -> str:
    for d in (cwd, root):
        venv = d / ".venv" / "bin" / "python"
        if venv.exists():
            return f"{shlex.quote(str(venv))} -m pytest"
    return "python3 -m pytest"


def _py_key(nodeid: str) -> str:
    _, _, rest = nodeid.partition("::")
    return re.sub(r"\[.*\]$", "", rest)


def run_pytest(group: Group, root: Path, command: str | None, scratch: Path) -> list[Outcome]:
    plugin_dir = scratch / "plugin"
    plugin_dir.mkdir(exist_ok=True)
    shutil.copy(HERE / "pytest_plugin.py", plugin_dir / "red_on_logic_pytest_plugin.py")
    out = scratch / "pytest.jsonl"
    env = _env(scratch)
    env["RED_ON_LOGIC_OUT"] = str(out)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(plugin_dir), env.get("PYTHONPATH")]))
    argv = shlex.split(command or default_pytest(root, group.cwd))
    files = [os.path.relpath(root / f, group.cwd) for f in group.files]
    argv += ["-p", "red_on_logic_pytest_plugin", "--continue-on-collection-errors", "-q"]
    output = _run([*argv, *files], group.cwd, env)
    if not out.exists() and "while loading conftest" in output:
        # A shared helper (a conftest and what it imports) failed before any test ran:
        # every file is red on import, with the helper's error as the reason.
        errors = [ln[1:].strip() for ln in output.splitlines() if ln.startswith("E ")]
        reason = errors[-1] if errors else "a conftest failed to load"
        message = f"conftest failed to load: {reason}"
        return [Outcome(f, f, "error", message=message, file_level=True) for f in group.files]
    if not out.exists():
        raise _no_report("pytest", output)
    return parse_pytest(out.read_text(), root)


def parse_pytest(text: str, root: Path) -> list[Outcome]:
    phases: dict[str, list[dict[str, Any]]] = {}
    outcomes: list[Outcome] = []
    for line in text.splitlines():
        record: dict[str, Any] = json.loads(line)
        base = Path(record["root"])
        if "collect" in record:
            file = _rel(base / str(record["collect"]).split("::")[0], root)
            outcomes.append(
                Outcome(file, file, "error", message=str(record["message"]), file_level=True)
            )
            continue
        phases.setdefault(str(record["nodeid"]), []).append(record)
    for nodeid, records in phases.items():
        root_dir = Path(records[0]["root"])
        file = _rel(root_dir / nodeid.split("::")[0], root)
        test_id = f"{file}::{nodeid.partition('::')[2]}"
        status, kind, message = "passed", "", ""
        for r in records:
            exc: dict[str, Any] | None = r["exc"]
            detail = f"{exc['type']}: {exc['message']}".rstrip(": ") if exc else ""
            if r["outcome"] == "skipped" and status == "passed":
                status, message = "skipped", detail
            elif r["outcome"] == "failed" and status in ("passed", "skipped"):
                if r["when"] == "call" and exc:
                    status, message = "failed", detail
                    kind = python_kind(exc["type"], exc["message"], assertion=exc["assertion"])
                    if kind == "shape":
                        status = "error"
                else:
                    status, message = "error", f"{r['when']} failed: {detail}"
        if status == "passed" and not any(
            r["when"] == "call" and r["outcome"] == "passed" for r in records
        ):
            # No passing call phase: the process died mid-test, so it never finished.
            status, message = "skipped", "the test did not finish (its process ended)"
        outcomes.append(Outcome(file, test_id, status, kind, message, key=_py_key(nodeid)))
    return outcomes


def _js_status(raw: str) -> str:
    return {"passed": "passed", "failed": "failed"}.get(raw, "skipped")


def _js_failure(message: str) -> tuple[str, str, str]:
    kind = js_kind(message)
    first = message.strip().splitlines()[0] if message.strip() else ""
    return ("error" if kind == "shape" else "failed"), kind, first[:300]


def parse_jest_json(text: str, root: Path) -> list[Outcome]:
    """vitest's json reporter and jest's --json share one shape."""
    data: dict[str, Any] = json.loads(text)
    outcomes: list[Outcome] = []
    suites: list[dict[str, Any]] = data.get("testResults", [])
    for suite in suites:
        file = _rel(str(suite["name"]), root)
        cases: list[dict[str, Any]] = suite.get("assertionResults") or []
        if not cases:
            if suite.get("status") == "failed" or suite.get("message"):
                message = next(
                    (
                        ln.strip()
                        for ln in str(suite.get("message", "")).splitlines()
                        if ln.strip() and "Test suite failed to run" not in ln
                    ),
                    "the file failed to load",
                )
                outcomes.append(Outcome(file, file, "error", message=message, file_level=True))
            continue
        for case in cases:
            title = str(case["title"])
            ancestors: list[str] = case.get("ancestorTitles") or []
            titles = [*map(str, ancestors), title]
            status = _js_status(str(case.get("status", "")))
            kind, message = "", ""
            if status == "failed":
                failures: list[str] = case.get("failureMessages") or [""]
                status, kind, message = _js_failure(str(failures[0]))
            location: dict[str, Any] = case.get("location") or {}
            line = location.get("line")
            outcomes.append(
                Outcome(
                    file,
                    f"{file} > {' > '.join(titles)}",
                    status,
                    kind,
                    message,
                    title=title,
                    line=line if isinstance(line, int) else None,
                )
            )
    return outcomes


def parse_node(text: str, root: Path) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for line in text.splitlines():
        r: dict[str, Any] = json.loads(line)
        file = _rel(r["file"], root)
        if r["fileLevel"]:
            message = r["message"] or "the file failed to load"
            outcomes.append(Outcome(file, file, "error", message=message, file_level=True))
            continue
        status, kind, message = r["status"], "", ""
        if status == "failed":
            status, kind, message = _js_failure(r["message"])
        outcomes.append(
            Outcome(
                file,
                f"{file} > {r['full']}",
                status,
                kind,
                message,
                title=r["title"],
                line=r["line"],
            )
        )
    return outcomes


def run_js(group: Group, root: Path, commands: Commands, scratch: Path) -> list[Outcome]:
    env = _env(scratch)
    files = [os.path.relpath(root / f, group.cwd) for f in group.files]
    if group.runner == "vitest":
        out = scratch / "vitest.json"
        argv = shlex.split(commands.vitest)
        argv += [*files, "--reporter=json", f"--outputFile={out}", "--includeTaskLocation"]
    elif group.runner == "jest":
        out = scratch / "jest.json"
        argv = shlex.split(commands.jest)
        argv += ["--json", f"--outputFile={out}", "--testLocationInResults", "--no-cache"]
        argv += ["--runTestsByPath", *files]
    else:
        out = scratch / "node.jsonl"
        argv = shlex.split(commands.node)
        argv += ["--test", f"--test-reporter={(HERE / 'node_reporter.mjs').as_uri()}"]
        argv += [f"--test-reporter-destination={out}", *files]
    output = _run(argv, group.cwd, env)
    if not out.exists():
        raise _no_report(group.runner, output)
    text = out.read_text()
    if group.runner == "node":
        return parse_node(text, root)
    try:
        return parse_jest_json(text, root)
    except (ValueError, KeyError) as e:
        raise ToolError(f"{group.runner} wrote results this check cannot read: {e}") from e


def _junit_file(case: ET.Element, cwd: Path, root: Path, files: tuple[str, ...]) -> str:
    """The test file a JUnit case belongs to: its `file` attribute, else its dotted
    `classname` matched to one of the run's files (`checks.test_calc` -> checks/test_calc.py),
    else, with no classname at all, the run's only file."""
    raw = case.get("file")
    if raw:
        return _rel(raw if Path(raw).is_absolute() else cwd / raw, root)
    classname = case.get("classname") or ""
    for f in files:
        module = os.path.splitext(os.path.relpath(root / f, cwd))[0].replace(os.sep, ".")
        if classname == module or classname.startswith(module + "."):
            return f
    if classname and (cwd / classname).exists():
        return _rel(cwd / classname, root)
    return files[0] if len(files) == 1 and not classname else classname


def parse_junit(text: str, cwd: Path, root: Path, files: tuple[str, ...] = ()) -> list[Outcome]:
    try:
        tree = ET.fromstring(text)  # noqa: S314 - the tested project's own runner's report
    except ET.ParseError as e:
        raise ToolError(f"the command's JUnit report cannot be read: {e}") from e
    outcomes: list[Outcome] = []
    for case in tree.iter("testcase"):
        file = _junit_file(case, cwd, root, files)
        name = case.get("name", "")
        status, message = "passed", ""
        for tag, mapped in (("error", "error"), ("failure", "failed"), ("skipped", "skipped")):
            child = case.find(tag)
            if child is not None:
                status = mapped
                message = (child.get("message") or child.text or "").strip().splitlines()[:1]
                message = message[0][:300] if message else ""
                break
        kind = "assertion" if status == "failed" else ""
        outcomes.append(Outcome(file, f"{file}::{name}", status, kind, message, title=name))
    return outcomes


def run_command(group: Group, root: Path, command: str, scratch: Path) -> list[Outcome]:
    out = scratch / "junit.xml"
    env = _env(scratch)
    files = " ".join(shlex.quote(os.path.relpath(root / f, group.cwd)) for f in group.files)
    env["RED_ON_LOGIC_JUNIT"] = str(out)
    env["RED_ON_LOGIC_FILES"] = files
    line = command.replace("{junit}", shlex.quote(str(out))).replace("{files}", files)
    output = _run(line, group.cwd, env, shell=True)  # noqa: S604 - the owner's command
    if not out.exists():
        raise _no_report("the command", output)
    return parse_junit(out.read_text(), group.cwd, root, group.files)


def run_group(group: Group, root: Path, commands: Commands) -> list[Outcome]:
    with tempfile.TemporaryDirectory(prefix="red-on-logic-") as tmp:
        scratch = Path(tmp)
        if group.runner == "pytest":
            outcomes = run_pytest(group, root, commands.pytest, scratch)
        elif group.runner == "command":
            if not commands.command:
                raise ToolError("--runner command needs --command")
            outcomes = run_command(group, root, commands.command, scratch)
        else:
            outcomes = run_js(group, root, commands, scratch)
    wanted = set(group.files)
    return _distinct([o for o in outcomes if o.file in wanted])


def _distinct(outcomes: list[Outcome]) -> list[Outcome]:
    """Two tests with one id (the same title twice) get `#2`, `#3` in run order, so the
    head's and the base's are matched one to one and never share a verdict."""
    seen: dict[str, int] = {}
    out: list[Outcome] = []
    for o in outcomes:
        seen[o.id] = seen.get(o.id, 0) + 1
        out.append(o if seen[o.id] == 1 else replace(o, id=f"{o.id} #{seen[o.id]}"))
    return out
