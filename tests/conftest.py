"""Planted repositories: a base commit on main and a pull request's head commit on a branch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from red_on_logic.cli import main

JS_MODULES = Path(__file__).parent / "js" / "node_modules"
PYTEST = f"{sys.executable} -m pytest"


def git(root: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    done = subprocess.run(
        ["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout


class Planted:
    """A repository with a base commit on `main` and a head commit on `feature`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        git(root, "init", "-q", "-b", "main")
        self.write(".gitignore", "node_modules\n__pycache__/\n.pytest_cache/\n")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def delete(self, rel: str) -> None:
        (self.root / rel).unlink()

    def commit(self, message: str = "change") -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.root, "rev-parse", "HEAD").strip()

    def base(self, message: str = "base") -> str:
        sha = self.commit(message)
        git(self.root, "checkout", "-q", "-b", "feature")
        return sha

    def link_node_modules(self, rel: str = "") -> None:
        if not JS_MODULES.is_dir():
            pytest.fail("the JavaScript runners are not installed: run `npm ci` in tests/js")
        (self.root / rel / "node_modules").symlink_to(JS_MODULES)

    def tree(self) -> dict[str, str]:
        """Every tracked and untracked, non-ignored file's text, to prove a run left no trace."""
        listed = git(self.root, "ls-files", "-co", "--exclude-standard").split()
        return {f: (self.root / f).read_text() for f in sorted(listed)}

    def run(self, *args: str) -> tuple[int, dict[str, Any], str]:
        out = self.root.parent / f"{self.root.name}-report.json"
        code = main(["--repo", str(self.root), "--base", "main", "--json", str(out), *args])
        report: dict[str, Any] = json.loads(out.read_text()) if out.exists() else {}
        return code, report, report.get("text", "")


@pytest.fixture
def planted(tmp_path: Path) -> Planted:
    root = tmp_path / "repo"
    root.mkdir()
    return Planted(root)


def verdicts(report: dict[str, Any]) -> dict[str, str]:
    """Test id -> verdict, for the judged tests only."""
    return {t["id"]: t["verdict"] for t in report["tests"] if t["judged"]}
