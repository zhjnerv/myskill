"""Exercise actual Windows junction deployment in an isolated fixture."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows PowerShell junction tests")
class SkillDeployTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="myskill-deploy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.profile = self.root / "profile"
        self.target = self.profile / ".codex" / "skills"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "skills").mkdir()
        self.source = self.repo / "vendor" / "package" / "skills" / "nested-skill"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: nested-skill\n---\n", encoding="utf-8")
        for name in ("skill-deploy.ps1", "_common.ps1"):
            shutil.copyfile(SCRIPTS / name, self.repo / "scripts" / name)
        (self.repo / "registry.json").write_text(json.dumps({"version": 2, "skills": [
            {"name": "package", "origin": "vendored", "localPrefix": "vendor/package"}
        ]}), encoding="utf-8")

    def deploy(self, *args: str, success: bool = True) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["USERPROFILE"] = str(self.profile)
        result = subprocess.run([
            POWERSHELL, "-NoProfile", "-File", str(self.repo / "scripts" / "skill-deploy.ps1"),
            "-TargetRoot", str(self.target), *args,
        ], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_named_nested_skill_and_repeat(self) -> None:
        self.deploy("-Name", "nested-skill")
        self.assertTrue((self.target / "nested-skill").is_junction())
        self.assertEqual((self.target / "nested-skill").resolve(), self.source.resolve())
        self.deploy("-Name", "nested-skill")
        self.assertFalse((self.profile / ".codex" / "vendor").exists())

    def test_dry_run_creates_nothing(self) -> None:
        self.deploy("-DryRun")
        # PowerShell may create its own startup cache under USERPROFILE.
        self.assertFalse((self.profile / ".codex").exists())

    def test_unknown_name_creates_nothing(self) -> None:
        self.deploy("-Name", "unknown", success=False)
        self.assertFalse((self.profile / ".codex").exists())

    def test_full_deployment_includes_top_level_and_package(self) -> None:
        top = self.repo / "skills" / "top-skill"
        top.mkdir()
        (top / "SKILL.md").write_text("top", encoding="utf-8")
        self.deploy()
        self.assertEqual((self.target / "top-skill").resolve(), top.resolve())
        self.assertEqual((self.target / "nested-skill").resolve(), self.source.resolve())
        self.assertEqual((self.profile / ".codex" / "vendor" / "package").resolve(),
                         (self.repo / "vendor" / "package").resolve())

    def test_force_backs_up_existing_directory(self) -> None:
        existing = self.target / "nested-skill"
        existing.mkdir(parents=True)
        (existing / "keep.txt").write_text("user content", encoding="utf-8")
        self.deploy("-Name", "nested-skill")
        self.assertFalse(existing.is_junction())
        self.deploy("-Name", "nested-skill", "-Force")
        self.assertEqual(existing.resolve(), self.source.resolve())
        backups = list(self.target.glob("nested-skill.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "keep.txt").read_text(), "user content")


if __name__ == "__main__":
    unittest.main()
