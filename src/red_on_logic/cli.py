"""red-on-logic: a pull request's new or changed tests must fail on the base branch's code.

    red-on-logic                      # this branch against origin/HEAD (or origin/main, main)
    red-on-logic --base main --json out.json --summary summary.md

It runs the changed test files twice in this checkout: once as they are (the head), then
with every changed code file put back to the base's version, the tests and their support
files kept at the head's. Then it puts the checkout back. A judged test (new, or its own
lines changed) proves the change when it passes on the head and fails on the base with a
wrong answer: an assertion, or a crash in the code under test. Failing because a module,
name or argument is missing is red on import, not on logic, and proves nothing.

Exit 0 when at least one judged test proves the change, or when a commit trailer or label
`red-on-logic: not applicable (<reason>)` skips the check; 1 when none does; 2 when the
check itself could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import FrameType

from red_on_logic.report import Report, Row, render_markdown, render_text, verdict_of
from red_on_logic.runners import RUNNERS, Commands, Group, Outcome, ToolError, detect, run_group
from red_on_logic.select import (
    hunk_lines,
    is_code,
    is_test_file,
    js_touched,
    matches_any,
    python_touched,
)
from red_on_logic.skip import SkipError, find_skip


def git(root: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["git", "--literal-pathspecs", *args],
        cwd=root,
        input=stdin,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if done.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _default_base(root: Path) -> str:
    for ref in ("origin/HEAD", "origin/main", "main"):
        ok = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if ok.returncode == 0:
            return ref
    raise ToolError("no base given and none of origin/HEAD, origin/main or main exists")


def _changes(root: Path, base: str, head: str) -> list[tuple[str, str]]:
    out = git(root, "diff", "--name-status", "--no-renames", "-z", base, head)
    parts = out.split("\0")
    return [(parts[i][0], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


@contextmanager
def _terminate_as_interrupt() -> Generator[None]:
    """SIGTERM (a cancelled job) and SIGHUP (a closed terminal) unwind like Ctrl-C, so the
    checkout is put back."""

    def raise_interrupt(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        raise KeyboardInterrupt

    previous = {s: signal.signal(s, raise_interrupt) for s in STOP_SIGNALS}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def _branch(root: Path) -> str:
    done = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def _restore(root: Path, head: str, branch: str, swapped: list[str]) -> None:
    """Put the checkout back at the head, with SIGTERM and SIGHUP held off until it is done
    (Ctrl-C still stops a git that hangs).
    Refuses when HEAD or the branch moved during the run: a reset would move the new
    branch to this head."""
    held = {s: signal.signal(s, signal.SIG_IGN) for s in STOP_SIGNALS}
    try:
        now = git(root, "rev-parse", "HEAD").strip()
        if now != head or _branch(root) != branch:
            paths = " ".join(shlex.quote(p) for p in swapped)
            raise ToolError(
                f"HEAD moved during the run, so the checkout was not reset. These files may"
                f" still hold the base's version: {paths or '(none)'}. To put them back:"
                f" git checkout {head} -- <file>"
            )
        git(root, "reset", "-q", "--hard", head)
    finally:
        for s, handler in held.items():
            signal.signal(s, handler)


@contextmanager
def base_code(root: Path, base: str, head: str, code: list[tuple[str, str]]) -> Generator[None]:
    """The checkout with every changed code file at the base's version, then put back."""
    restore = [p for s, p in code if s != "A"]
    remove = [p for s, p in code if s == "A"]
    in_the_way = [p for s, p in code if s == "D" and os.path.lexists(root / p)]
    if in_the_way:
        raise ToolError(
            "these files are not tracked on this branch but exist here, and the base run would"
            f" overwrite them: {', '.join(in_the_way)}. Move them aside first"
        )
    branch = _branch(root)
    try:
        if restore:
            git(root, "checkout", base, "--pathspec-from-file=-", "--pathspec-file-nul",
                stdin="\0".join(restore))  # fmt: skip
        if remove:
            git(root, "rm", "-q", "-f", "--pathspec-from-file=-", "--pathspec-file-nul",
                stdin="\0".join(remove))  # fmt: skip
        yield
    finally:
        _restore(root, head, branch, restore + remove)


def _groups(
    root: Path, files: list[str], runner: str, cwd: Path | None
) -> tuple[list[Group], list[str]]:
    by: dict[tuple[str, Path], list[str]] = {}
    unrunnable: list[str] = []
    for f in files:
        if runner != "auto":
            by.setdefault((runner, cwd or root), []).append(f)
            continue
        found = detect(f, root)
        if found is None:
            unrunnable.append(f)
        else:
            by.setdefault(found, []).append(f)
    groups = [
        Group(r, d, tuple(fs))
        for (r, d), fs in sorted(by.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))
    ]
    return groups, unrunnable


def _run_all(groups: list[Group], root: Path, commands: Commands) -> dict[str, list[Outcome]]:
    found: dict[str, list[Outcome]] = {}
    for group in groups:
        for o in run_group(group, root, commands):
            found.setdefault(o.file, []).append(o)
    return found


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    try:
        return [re.compile(p) for p in patterns]
    except re.error as e:
        raise ToolError(f"--import-pattern is not a valid regular expression: {e}") from e


def _mark_shapes(
    found: dict[str, list[Outcome]], patterns: list[re.Pattern[str]]
) -> dict[str, list[Outcome]]:
    """A base failure whose message matches one of the repository's own patterns (its
    words for a name the old code does not know) is red on import, not a wrong answer.
    A pattern is tried on the message as stored (`AssertionError: unknown service: b`)
    and on the text after its type, so `^unknown service` matches too."""

    def matches(message: str) -> bool:
        bare = message.split(": ", 1)[1] if ": " in message else message
        return any(p.search(message) or p.search(bare) for p in patterns)

    return {
        f: [
            replace(o, status="error", kind="shape")
            if o.status == "failed" and matches(o.message)
            else o
            for o in outcomes
        ]
        for f, outcomes in found.items()
    }


def _judged(
    runner: str, source: str, outcomes: list[Outcome], changed: set[int] | None
) -> list[bool]:
    if runner == "pytest":
        return python_touched(source, [o.key for o in outcomes], changed)
    if runner == "command":
        return [True for _ in outcomes]
    return js_touched(source, [(o.title, o.line) for o in outcomes], changed)


def _rows(
    groups: list[Group],
    root: Path,
    head: dict[str, list[Outcome]],
    base: dict[str, list[Outcome]],
    lines: dict[str, set[int]],
    added: set[str],
) -> list[Row]:
    rows: list[Row] = []
    for group in groups:
        for file in group.files:
            head_tests = [o for o in head.get(file, []) if not o.file_level]
            head_error = next((o for o in head.get(file, []) if o.file_level), None)
            base_by_id = {o.id: o for o in base.get(file, []) if not o.file_level}
            base_error = next((o for o in base.get(file, []) if o.file_level), None)
            if head_error and not head_tests:
                rows.append(Row(file, file, group.runner, True, head_error, None))
                continue
            if not head_tests:
                rows.append(Row(file, file, group.runner, True, None, None))
                continue
            source = (root / file).read_text(errors="replace")
            changed = None if file in added else lines.get(file, set())
            flags = _judged(group.runner, source, head_tests, changed)
            for o, judged in zip(head_tests, flags, strict=True):
                rows.append(
                    Row(o.id, file, group.runner, judged, o, base_by_id.get(o.id, base_error))
                )
    return rows


def check(args: argparse.Namespace) -> Report:
    patterns = compile_patterns(args.import_pattern)
    root = Path(git(Path(args.repo), "rev-parse", "--show-toplevel").strip())
    head = git(root, "rev-parse", "HEAD").strip()
    base_ref = args.base or _default_base(root)
    base = git(root, "merge-base", base_ref, head).strip()
    messages = git(root, "log", "--format=%B%x00", f"{base}..{head}").split("\0")
    try:
        skip = find_skip(messages, list(args.label))
    except SkipError as e:
        return Report("invalid-skip", base, head, note=str(e))
    if skip:
        return Report("skipped", base, head, skip=skip)

    extra = tuple(args.test_paths)
    changes = _changes(root, base, head)
    if args.runner == "command":
        if not extra:
            raise ToolError("--runner command needs --test-paths to say which files are tests")
        tests = [p for s, p in changes if s != "D" and matches_any(p, extra)]
    else:
        tests = [p for s, p in changes if s != "D" and is_test_file(p, extra)]
    code = [(s, p) for s, p in changes if is_code(p, extra, tuple(args.code_paths))]
    report = Report("no-tests", base, head, changes_code=bool(code), test_files=len(tests))
    if not tests:
        return report

    cwd = (root / args.working_directory) if args.working_directory else None
    groups, report.unrunnable = _groups(root, tests, args.runner, cwd)
    if not groups:
        report.result = "not-proven"
        return report
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ToolError(
            "the checkout has uncommitted changes to tracked files: commit or stash them first"
        )
    commands = Commands(
        pytest=args.pytest,
        vitest=args.vitest or Commands.vitest,
        jest=args.jest or Commands.jest,
        node=args.node or Commands.node,
        command=args.command,
    )
    lines = {
        f: hunk_lines(
            git(
                root,
                "-c",
                "core.quotePath=false",
                "diff",
                "-U0",
                "--no-renames",
                "--no-color",
                "--no-ext-diff",
                base,
                head,
                "--",
                f,
            )
        )
        for f in tests
    }
    added = {p for s, p in changes if s == "A"}
    with _terminate_as_interrupt():
        head_outcomes = _run_all(groups, root, commands)
        with base_code(root, base, head, code):
            base_outcomes = _run_all(groups, root, commands)
    if patterns:
        base_outcomes = _mark_shapes(base_outcomes, patterns)
    report.rows = _rows(groups, root, head_outcomes, base_outcomes, lines, added)
    judged = [r for r in report.rows if r.judged]
    if any(verdict_of(r) == "proven" for r in judged):
        report.result = "proven"
    elif judged:
        report.result = "not-proven"
    return report


def as_json(report: Report, text: str) -> dict[str, object]:
    return {
        "result": report.result,
        "base": report.base,
        "head": report.head,
        "skip": {"reason": report.skip.reason, "source": report.skip.source}
        if report.skip
        else None,
        "unrunnable": report.unrunnable,
        "tests": [
            {
                "id": r.id,
                "file": r.file,
                "runner": r.runner,
                "judged": r.judged,
                "verdict": verdict_of(r),
                "head": r.head.status if r.head else None,
                "base": r.base.status if r.base else None,
                "detail": (r.base.message if r.base else "") or (r.head.message if r.head else ""),
            }
            for r in report.rows
        ],
        "text": text,
    }


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="red-on-logic", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("--repo", default=".", help="the checkout (default: here)")
    p.add_argument("--base", help="the base branch or commit (default: origin/HEAD)")
    p.add_argument("--runner", choices=("auto", *RUNNERS), default="auto")
    p.add_argument("--pytest", help="the pytest command (default: .venv/bin/python -m pytest)")
    p.add_argument("--vitest", help=f"the vitest command (default: {Commands.vitest})")
    p.add_argument("--jest", help=f"the jest command (default: {Commands.jest})")
    p.add_argument("--node", help="the node command (default: node)")
    p.add_argument(
        "--command",
        help="with --runner command: a shell command that runs {files} and writes JUnit to {junit}",
    )
    p.add_argument(
        "--test-paths",
        action="append",
        default=[],
        help="a glob of more test files (repeatable); with --runner command, the only ones",
    )
    p.add_argument(
        "--code-paths",
        action="append",
        default=[],
        help="a glob of files that are code though not source (templates, SQL); repeatable",
    )
    p.add_argument(
        "--import-pattern",
        action="append",
        default=[],
        help="a regular expression: a base failure whose message matches is red on import"
        " (the repository's words for an unknown name, e.g. 'unknown service'); repeatable",
    )
    p.add_argument("--working-directory", help="with --runner, where the runner runs")
    p.add_argument("--label", action="append", default=[], help="a pull request label (repeatable)")
    p.add_argument("--json", help="also write the report as JSON here")
    p.add_argument("--summary", help="also append the report as Markdown here")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = check(args)
    except ToolError as e:
        print(f"red-on-logic: could not run: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("red-on-logic: stopped; the checkout is back as it was", file=sys.stderr)
        return 130
    text = render_text(report)
    print(text)
    if args.json:
        Path(args.json).write_text(json.dumps(as_json(report, text), indent=2) + "\n")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as out:
            out.write(render_markdown(report) + "\n")
    return 0 if report.result in ("proven", "skipped") else 1


def entry() -> None:
    sys.exit(main())
