"""中国专利共享本地法源路径合同。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = ROOT / "references" / "cn-legal-sources"
SOURCE_PATHS = (
    SHARED_ROOT / "专利法(2020-10-17).md",
    SHARED_ROOT / "专利法实施细则(2023-12-21).md",
    SHARED_ROOT / "审查指南2026MD" / "guide-full.md",
)
CN_SKILLS = (
    "cn-patent-application-creator",
    "cn-patent-claims-analyzer",
    "cn-patent-formalities-reviewer",
    "cn-patent-reviewer",
    "cn-patent-specification-reviewer",
)
RUNTIME_ROOT = "${CN_PATENT_CREATOR_ROOT:-${CLAUDE_PATENT_CREATOR_CN_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CODEX_HOME:-$HOME/.codex}/vendor/claude-patent-creator-cn}}}/references/cn-legal-sources/"


class LocalLegalSourcesTests(unittest.TestCase):
    def test_shared_legal_sources_exist_and_are_nonempty_utf8(self):
        for path in SOURCE_PATHS:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())
                raw = path.read_bytes()
                self.assertTrue(raw)
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                raw.decode("utf-8")

        chapters = SHARED_ROOT / "审查指南2026MD" / "chapters"
        self.assertTrue(chapters.is_dir())
        self.assertGreater(len(list(chapters.glob("*.md"))), 0)

    def test_all_cn_skills_point_to_the_shared_runtime_root(self):
        for skill in CN_SKILLS:
            with self.subTest(skill=skill):
                content = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
                prefix = RUNTIME_ROOT[: -len("/references/cn-legal-sources/")]
                # 允许两种写法：直接写完整运行根路径，或先定义 ROOT="<完整运行根>" 再以 $ROOT 引用法源。
                uses_root_variable = f'ROOT="{prefix}"' in content and "$ROOT/references/cn-legal-sources/" in content
                self.assertTrue(RUNTIME_ROOT in content or uses_root_variable, skill)


if __name__ == "__main__":
    unittest.main()
