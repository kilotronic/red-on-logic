"""Each judged test's verdict, and the report in plain words: text, Markdown and JSON."""

from __future__ import annotations

from dataclasses import dataclass, field

from red_on_logic.runners import Outcome
from red_on_logic.skip import EXAMPLE, Skip

LABELS = {
    "proven": "fails on the base (proves the change)",
    "vacuous": "passes on the base (proves nothing)",
    "red-on-import": "red on import, not logic",
    "broken-on-head": "fails on this branch too",
    "not-run": "did not run",
}
ORDER = list(LABELS)


@dataclass(frozen=True)
class Row:
    id: str
    file: str
    runner: str
    judged: bool
    head: Outcome | None
    base: Outcome | None


@dataclass
class Report:
    result: str  # proven, not-proven, no-tests, skipped, invalid-skip
    base: str = ""
    head: str = ""
    skip: Skip | None = None
    rows: list[Row] = field(default_factory=lambda: [])
    unrunnable: list[str] = field(default_factory=lambda: [])
    changes_code: bool = True
    note: str = ""


def verdict_of(row: Row) -> str:
    head, base = row.head, row.base
    if head is None or head.status == "skipped":
        return "not-run"
    if head.status != "passed":
        return "broken-on-head"
    if base is None or base.status == "skipped":
        return "not-run"
    return {"passed": "vacuous", "failed": "proven"}.get(base.status, "red-on-import")


def detail_of(row: Row) -> str:
    verdict = verdict_of(row)
    if verdict == "broken-on-head" and row.head:
        return row.head.message
    if verdict == "not-run":
        if row.head is None:
            return f"{row.runner} reported no tests in it on this branch"
        if row.head.status == "skipped":
            return "skipped on this branch"
        return "skipped on the base" if row.base else "not run on the base"
    if row.base and row.base.status == "failed" and row.base.kind == "crash":
        return f"raised {row.base.message}"
    return row.base.message if row.base else ""


HINTS = {
    "vacuous": (
        "A test that passes on the old code does not test this change: make it fail on the old"
        " code with a wrong answer."
    ),
    "red-on-import": (
        "A test that fails only because a module, name or argument is missing proves nothing"
        " about logic. Test behaviour the old code gets wrong, or land the new name first"
        " (with a wrong answer) in its own pull request."
    ),
    "broken-on-head": "A test that fails on this branch too proves nothing until it passes here.",
}
SKIP_HINT = (
    f"If this pull request needs no proof (a pure refactor, tests or docs only), say why in a"
    f" commit trailer or a label: `{EXAMPLE}`."
)


def _short(sha: str) -> str:
    return sha[:12]


def _headline(report: Report) -> str:
    judged = [r for r in report.rows if r.judged]
    proven = [r for r in judged if verdict_of(r) == "proven"]
    if report.result == "skipped" and report.skip:
        return f"red-on-logic: skipped by a {report.skip.source}: {report.skip.reason}"
    if report.result == "invalid-skip":
        return f"red-on-logic: not proven. {report.note}"
    if report.result == "no-tests":
        return "red-on-logic: not proven. This pull request has no new or changed tests."
    n = len(judged)
    if n == 0 and report.unrunnable:
        return "red-on-logic: not proven. No changed test file could be run."
    noun = "test" if n == 1 else "tests"
    if report.result == "proven":
        return (
            f"red-on-logic: proven. {len(proven)} of {n} new or changed {noun} fail"
            f"{'s' if len(proven) == 1 else ''} on the base's code with a wrong answer."
        )
    if n == 1:
        return (
            "red-on-logic: not proven. The new or changed test does not fail on the base's code"
            " with a wrong answer."
        )
    return (
        f"red-on-logic: not proven. None of the {n} new or changed tests fails on the base's"
        " code with a wrong answer."
    )


def render_text(report: Report) -> str:
    lines = [_headline(report)]
    if report.base:
        lines.append(f"Base {_short(report.base)}, head {_short(report.head)}.")
    judged = sorted(
        (r for r in report.rows if r.judged), key=lambda r: (ORDER.index(verdict_of(r)), r.id)
    )
    if judged:
        lines.append("")
        width = max(len(LABELS[verdict_of(r)]) for r in judged)
        for r in judged:
            lines.append(f"  {LABELS[verdict_of(r)]:<{width}}  {r.id}")
            if detail := detail_of(r):
                lines.append(f"  {'':<{width}}    {detail}")
    others = [r for r in report.rows if not r.judged]
    if others:
        lines += ["", f"{len(others)} unchanged test(s) in the changed files ran too; not judged."]
    for f in report.unrunnable:
        lines.append(f"No test runner found for {f}: name one with --runner.")
    if report.result in ("proven", "skipped"):
        return "\n".join(lines)
    seen = {verdict_of(r) for r in judged}
    hints = [HINTS[v] for v in HINTS if v in seen]
    if report.result == "not-proven" and not report.changes_code:
        hints.insert(
            0, "This pull request changes no code, only tests, so every test passes on the base."
        )
    return "\n".join([*lines, "", *hints, SKIP_HINT])


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Report) -> str:
    text = render_text(report).splitlines()
    out = [f"### {_cell(text[0])}", ""]
    judged = [r for r in report.rows if r.judged]
    if judged:
        out += ["| Test | Verdict | Detail |", "| --- | --- | --- |"]
        for r in sorted(judged, key=lambda r: (ORDER.index(verdict_of(r)), r.id)):
            out.append(f"| {_cell(r.id)} | {LABELS[verdict_of(r)]} | {_cell(detail_of(r))} |")
        out.append("")
    tail = [ln for ln in text[1:] if ln and not ln.startswith("  ")]
    out += tail
    return "\n".join(out)
