#!/usr/bin/env python3
"""Regression tests for offline upstream skill synchronization."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("sync_upstream_skills.py")


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
        raise AssertionError(
            f"git {' '.join(args)} failed\n{result.stdout}{result.stderr}"
        )
    return result.stdout


class SubtreeRejoinTest(unittest.TestCase):
    def test_rejoins_renamed_prefix_and_syncs_next_update(self) -> None:
        with tempfile.TemporaryDirectory(prefix="myskill-subtree-test-") as temp_dir:
            temp = Path(temp_dir).resolve()
            source = temp / "source"
            destination = temp / "destination"
            run_git(temp, "init", "-b", "main", str(source))
            run_git(temp, "init", "-b", "main", str(destination))

            write_text(source / "package.txt", "v1\n")
            run_git(source, "add", ".")
            run_git(source, "commit", "-m", "source initial")

            source_url = source.as_uri()
            prefix = destination / "vendor" / "package"
            write_text(prefix / "package.txt", "v1\n")
            registry = {
                "version": 2,
                "skills": [
                    {
                        "name": "package",
                        "origin": "vendored",
                        "fork": source_url,
                        "upstream": source_url,
                        "branch": "main",
                        "subpath": None,
                        "localPrefix": "vendor/package",
                    }
                ],
            }
            write_text(
                destination / "registry.json",
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            )
            destination_scripts = destination / "scripts"
            destination_scripts.mkdir()
            shutil.copyfile(SCRIPT, destination_scripts / SCRIPT.name)
            run_git(destination, "add", ".")
            run_git(destination, "commit", "-m", "seed ordinary directory")

            result = subprocess.run(
                [sys.executable, str(destination_scripts / SCRIPT.name)],
                cwd=destination,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                (prefix / "package.txt").read_text(encoding="utf-8"),
                "v1\n",
            )
            history = run_git(
                destination,
                "log",
                "--format=%B",
                "--grep=^git-subtree-dir: vendor/package$",
            )
            self.assertIn("git-subtree-split: ", history)

            write_text(source / "package.txt", "v2\n")
            run_git(source, "add", ".")
            run_git(source, "commit", "-m", "source update")
            result = subprocess.run(
                [sys.executable, str(destination_scripts / SCRIPT.name)],
                cwd=destination,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                (prefix / "package.txt").read_text(encoding="utf-8"),
                "v2\n",
            )


if __name__ == "__main__":
    unittest.main()
