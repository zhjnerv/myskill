#!/usr/bin/env python3
"""Run the existing offline checks from any working directory (stdlib only)."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILLS = (
    "cn-trademark-goods-services-recommender",
    "cn-patent-fast-track-screener",
    "cn-office-action-prior-art-collector",
)


def headings(text: str) -> set[str]:
    """Slugs for the plain Markdown headings used in this repository."""
    result, counts = set(), {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        slug = re.sub(r"[^\w\s-]", "", title.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        result.add(f"{slug}-{count}" if count else slug)
        counts[slug] = count + 1
    return result


def check_files() -> None:
    json_count, link_count = 0, 0
    for name in SKILLS:
        skill = ROOT / "skills" / name
        entry = (skill / "SKILL.md").read_text(encoding="utf-8")
        if not re.search(rf"^name:\s*{re.escape(name)}\s*$", entry, re.M):
            raise ValueError(f"Skill name mismatch: {name}")
        for required in ("README.md", "LICENSE", "NOTICE.md"):
            if not (skill / required).is_file():
                raise ValueError(f"Missing {name}/{required}")
        for path in skill.rglob("*"):
            if path.suffix == ".json":
                packet = json.loads(path.read_text(encoding="utf-8"))
                json_count += 1
                if path.name == "evals.json":
                    for case in packet.get("evals", []):
                        for attachment in case.get("files", []):
                            if not (skill / attachment).is_file():
                                raise ValueError(f"Missing evaluation file: {attachment}")
            elif path.name.endswith(".json.gz"):
                json.loads(gzip.decompress(path.read_bytes()))
                json_count += 1
            elif path.suffix == ".py":
                compile(path.read_text(encoding="utf-8"), str(path), "exec")

    docs = [p for p in ROOT.rglob("*.md")
            if not any(x in p.relative_to(ROOT).parts for x in (".git", ".local"))]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"(?ms)^```.*?^```[^\n]*", "", text)
        for target in re.findall(r"\]\(([^\s)]+)\)", text):
            url = urlsplit(target.strip("<>"))
            if url.scheme or url.netloc:
                continue
            resolved = (path.parent / unquote(url.path)).resolve() if url.path else path
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                raise ValueError(f"Broken/local-outside link in {path.relative_to(ROOT)}: {target}")
            if url.fragment and resolved.suffix == ".md":
                if unquote(url.fragment) not in headings(resolved.read_text(encoding="utf-8")):
                    raise ValueError(f"Missing heading in {path.relative_to(ROOT)}: {target}")
            link_count += 1
    print(f"PASS: skill names, Python syntax, {json_count} JSON files, evaluation attachments, {link_count} local links", flush=True)


def run(name: str, *args: str) -> None:
    print(f"\nChecking {name}: {' '.join(args)}", flush=True)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONNOUSERSITE="1")
    subprocess.run(
        [sys.executable, "-B", "-S", "-X", "utf8", *args],
        cwd=ROOT / "skills" / name, env=env, check=True,
    )


def main() -> int:
    try:
        check_files()
        run(SKILLS[0], "-m", "unittest", "discover", "-s", "tests")
        run(SKILLS[1], "-m", "unittest", "discover", "-s", "tests")
        run(SKILLS[2], "scripts/selftest.py")
        run(SKILLS[0], "scripts/build_data.py", "--validate-only")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print("\nAll offline checks passed. Network and Agent evaluations were not run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
