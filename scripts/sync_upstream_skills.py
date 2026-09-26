#!/usr/bin/env python3
"""Pull vendored skills from their upstream repositories into this repo.

Designed to run on GitHub Actions. It does not update forks and does not open
upstream pull requests. On a content conflict, the file already in myskill is
kept whole; upstream changes to other files still merge.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "registry.json"


def git(*args: str, cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed\n{detail}")
    return result


def merge_in_progress() -> bool:
    return (REPO / ".git" / "MERGE_HEAD").exists()


def abort_merge() -> None:
    if merge_in_progress():
        git("merge", "--abort", check=False)


def unmerged_files() -> list[str]:
    result = git("diff", "--name-only", "--diff-filter=U", check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def skill_prefix(entry: dict) -> str:
    return (entry.get("localPrefix") or f"skills/{entry['name']}").strip("/")


def skill_tree(prefix: str) -> str:
    result = git("rev-parse", f"HEAD:{prefix}")
    return result.stdout.strip()


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def write_registry(data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    REGISTRY.write_text(text, encoding="utf-8", newline="\n")


class SkillFailure(Exception):
    pass


def mirror_for(url: str, branch: str, cache: dict[tuple[str, str], Path], root: Path) -> Path:
    key = (url, branch)
    if key in cache:
        return cache[key]
    slug = url.rstrip("/").removesuffix(".git").split("/")[-2:]
    dest = root / "--".join(slug)
    print(f"[clone] {url} -> {dest}", flush=True)
    git("clone", "--branch", branch, url, str(dest), cwd=root)
    cache[key] = dest
    return dest


def split_ref(mirror: Path, subpath: str, branch: str, name: str) -> str:
    ref = f"sync-{name}"
    print(f"[split] {name} {subpath}", flush=True)
    git("subtree", "split", f"--prefix={subpath}", "-b", ref, branch, cwd=mirror)
    return ref


def sync_skill(entry: dict, cache: dict[tuple[str, str], Path], mirror_root: Path) -> str:
    name = entry["name"]
    upstream = entry.get("upstream") or ""
    branch = entry.get("branch") or "main"
    subpath = entry.get("subpath") or ""
    if not upstream:
        print(f"[skip] {name} has no upstream")
        return "skipped"
    prefix = skill_prefix(entry)
    before = git("rev-parse", "HEAD").stdout.strip()
    mirror = mirror_for(upstream, branch, cache, mirror_root)
    ref = split_ref(mirror, subpath, branch, name) if subpath else branch
    print(f"[pull] {name} <- {upstream} ({ref})", flush=True)
    pull = git(
        "subtree", "pull", f"--prefix={prefix}", str(mirror), ref,
        "--squash", "-m", f"subtree: sync {name} from upstream",
        check=False,
    )
    if pull.returncode != 0:
        sys.stderr.write(pull.stderr)
        sys.stderr.write(pull.stdout)
        conflicts = unmerged_files()
        if not conflicts:
            abort_merge()
            raise SkillFailure(f"{name}: subtree pull failed before a merge")
        print(f"[keep-ours] {name}: {', '.join(conflicts)}", flush=True)
        for path in conflicts:
            git("checkout", "--ours", "--", path)
            git("add", "--", path)
        still = unmerged_files()
        if still:
            abort_merge()
            raise SkillFailure(f"{name}: could not keep local files: {', '.join(still)}")
        message = f"subtree: sync {name} from upstream\n\nKept the myskill version of:\n" + "\n".join(
            f"- {path}" for path in conflicts
        )
        git("commit", "-m", message)
    after = git("rev-parse", "HEAD").stdout.strip()
    if after == before:
        print(f"[current] {name}", flush=True)
        return "current"
    entry["lastSync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry["lastSyncTree"] = skill_tree(prefix)
    print(f"[updated] {name}", flush=True)
    return "updated"


def main() -> int:
    if git("status", "--porcelain").stdout.strip():
        print("working tree is dirty; refusing to sync", file=sys.stderr)
        return 1
    registry = load_registry()
    skills = [item for item in registry.get("skills", []) if item.get("origin") == "vendored"]
    if not skills:
        print("no vendored skills")
        return 0
    cache: dict[tuple[str, str], Path] = {}
    changed = False
    with tempfile.TemporaryDirectory(prefix="myskill-upstream-") as temp:
        mirror_root = Path(temp)
        for entry in skills:
            try:
                if sync_skill(entry, cache, mirror_root) == "updated":
                    changed = True
            except (SkillFailure, RuntimeError) as exc:
                abort_merge()
                print(f"[fail] {exc}", file=sys.stderr, flush=True)
                return 1
    if not changed:
        print("nothing to commit")
        return 0
    write_registry(registry)
    git("add", "--", "registry.json")
    git("commit", "-m", "registry: sync upstream skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
