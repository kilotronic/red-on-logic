"""A pull request that needs no proof says so, with a reason.

On a line of its own in any commit message (a trailer), or as a label:

    red-on-logic: not applicable (pure refactor, no behaviour change)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINE = re.compile(r"^\s*red-on-logic:\s*not applicable\b(.*)$", re.IGNORECASE)
REASON = re.compile(r"^\s*\((.*)\)\s*$")
EXAMPLE = "red-on-logic: not applicable (<reason>)"


class SkipError(Exception):
    """A skip was asked for without a reason."""


@dataclass(frozen=True)
class Skip:
    reason: str
    source: str


def _parse(line: str, source: str) -> Skip | None:
    match = LINE.match(line)
    if not match:
        return None
    reason = REASON.match(match[1])
    if not reason or not reason[1].strip():
        raise SkipError(f"The {source} `{line.strip()}` needs a reason: `{EXAMPLE}`.")
    return Skip(reason[1].strip(), source)


def find_skip(messages: list[str], labels: list[str]) -> Skip | None:
    """The first skip in the labels, then the commit messages; None when there is none."""
    for label in labels:
        if found := _parse(label, "label"):
            return found
    for message in messages:
        for line in message.splitlines():
            if found := _parse(line, "commit"):
                return found
    return None
