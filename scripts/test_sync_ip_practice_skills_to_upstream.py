#!/usr/bin/env python3
"""Regression tests for the myskill -> upstream skill back-sync guard."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync_ip_practice_skills_to_upstream.py")
SKILL = "demo-skill"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def run_git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed\n{result.stdout}{result.stderr}")
    return result.stdout


def load_module():
    spec = importlib.util.spec_from_file_location("back_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackSyncGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="myskill-back-sync-test-")
        self.root = Path(self.temp.name).resolve()
        self.upstream = self.root / "upstream"
        self.myskill = self.root / "myskill"

        run_git(self.root, "init", "-b", "main", str(self.upstream))
        self.write_upstream("v1\n")
        run_git(self.upstream, "add", ".")
        run_git(self.upstream, "commit", "-m", "upstream v1")
        self.v1_tree = run_git(self.upstream, "rev-parse", f"HEAD:skills/{SKILL}").strip()

        run_git(self.root, "init", "-b", "main", str(self.myskill))
        write_text(self.myskill / "skills" / SKILL / "SKILL.md", "v1\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_upstream(self, body: str) -> None:
        write_text(self.upstream / "skills" / SKILL / "SKILL.md", body)

    def write_registry(self, last_tree: str | None) -> None:
        registry = {
            "version": 2,
            "skills": [
                {
                    "name": SKILL,
                    "origin": "vendored",
                    "fork": self.upstream.as_uri(),
                    "upstream": self.upstream.as_uri(),
                    "branch": "main",
                    "subpath": f"skills/{SKILL}",
                    "localPrefix": f"skills/{SKILL}",
                    "lastSyncTree": last_tree,
                }
            ],
        }
        write_text(
            self.myskill / "registry.json",
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        )
        run_git(self.myskill, "add", ".")
        run_git(self.myskill, "commit", "-m", "seed myskill")

    def sync(self):
        module = load_module()
        module.REPO = self.myskill
        module.REGISTRY = self.myskill / "registry.json"
        module.UPSTREAM = self.upstream.as_uri()
        entry = module.load_entries()[SKILL]
        with tempfile.TemporaryDirectory(prefix="clone-") as clone_root:
            module.sync_one(SKILL, entry, Path(clone_root))

    def test_refuses_when_upstream_moved_after_last_sync(self) -> None:
        self.write_registry(self.v1_tree)
        write_text(self.myskill / "skills" / SKILL / "SKILL.md", "local edit\n")
        run_git(self.myskill, "add", ".")
        run_git(self.myskill, "commit", "-m", "local edit")

        self.write_upstream("v2 from upstream\n")
        run_git(self.upstream, "add", ".")
        run_git(self.upstream, "commit", "-m", "upstream v2")

        with self.assertRaises(RuntimeError) as caught:
            self.sync()
        self.assertIn("尚未拉回", str(caught.exception))
        self.assertNotIn(
            "myskill-sync",
            run_git(self.upstream, "branch", "--list", "myskill-sync/*"),
        )

    def test_refuses_when_baseline_tree_is_missing(self) -> None:
        self.write_registry(None)
        write_text(self.myskill / "skills" / SKILL / "SKILL.md", "local edit\n")
        run_git(self.myskill, "add", ".")
        run_git(self.myskill, "commit", "-m", "local edit")

        with self.assertRaises(RuntimeError) as caught:
            self.sync()
        self.assertIn("尚未拉回", str(caught.exception))

    def test_reports_current_without_pushing_when_directories_match(self) -> None:
        self.write_registry(self.v1_tree)

        self.sync()

        self.assertNotIn(
            "myskill-sync",
            run_git(self.upstream, "branch", "--list", "myskill-sync/*"),
        )


if __name__ == "__main__":
    unittest.main()
