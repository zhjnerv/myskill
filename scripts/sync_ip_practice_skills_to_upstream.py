#!/usr/bin/env python3
"""Open source-repository PRs for changed IP practice skills."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "registry.json"
UPSTREAM = "https://github.com/zhjnerv/ip-practice-workbench-skills"


def run(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd or REPO, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result


def load_entries() -> dict[str, dict]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {
        entry["name"]: entry for entry in registry["skills"]
        if entry.get("upstream") == UPSTREAM
    }


def changed_skills(entries: dict[str, dict]) -> list[str]:
    requested = [name.strip() for name in os.environ.get("SKILLS_INPUT", "").split(",") if name.strip()]
    if requested:
        unknown = sorted(set(requested) - entries.keys())
        if unknown:
            raise ValueError(f"Unknown skill names: {', '.join(unknown)}")
        return sorted(set(requested))

    before = os.environ.get("BEFORE_SHA", "")
    after = os.environ.get("AFTER_SHA", "")
    if not before or before == "0" * 40:
        return sorted(entries)
    paths = run(["git", "diff", "--name-only", f"{before}..{after}"]).stdout.splitlines()
    return sorted(
        name for name, entry in entries.items()
        if any(path == entry["localPrefix"] or path.startswith(entry["localPrefix"] + "/") for path in paths)
    )


def sync_one(name: str, entry: dict, temp_root: Path) -> None:
    branch = entry.get("branch") or "main"
    source_path = entry["localPrefix"]
    target_path = entry["subpath"]
    source = temp_root / name
    run(["git", "clone", "--depth", "1", UPSTREAM, str(source)])
    sync_branch = f"myskill-sync/{name}"
    branch_ref = run(["git", "ls-remote", "--heads", "origin", sync_branch], cwd=source, check=False)
    if branch_ref.stdout.strip():
        run(["git", "fetch", "origin", f"{sync_branch}:refs/remotes/origin/{sync_branch}"], cwd=source)
        run(["git", "checkout", "-B", sync_branch, f"origin/{sync_branch}"], cwd=source)
    else:
        run(["git", "checkout", "-B", sync_branch, f"origin/{branch}"], cwd=source)

    destination = source / target_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(REPO / source_path, destination)

    run(["git", "add", "-A", target_path], cwd=source)
    diff = run(["git", "diff", "--cached", "--quiet"], cwd=source, check=False)
    if diff.returncode == 0:
        print(f"[current] {name}")
        return
    run(["git", "config", "user.name", "github-actions[bot]"], cwd=source)
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=source)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    run(["git", "commit", "-m", f"sync({name}): update from myskill", "-m", f"Source: zhjnerv/myskill ({stamp})"], cwd=source)
    run(["git", "push", "origin", f"HEAD:refs/heads/{sync_branch}"], cwd=source)

    existing = run(
        ["gh", "pr", "list", "--repo", "zhjnerv/ip-practice-workbench-skills",
         "--head", f"zhjnerv:{sync_branch}", "--state", "open", "--json", "url", "--jq", ".[0].url"],
        check=False,
    )
    if existing.returncode:
        raise RuntimeError(existing.stderr.strip() or "Could not query existing pull requests")
    if existing.stdout.strip():
        run(["gh", "pr", "edit", existing.stdout.strip(), "--title", f"sync({name}): update from myskill",
             "--body", "Automated sync of the reviewed skill directory from `zhjnerv/myskill`."], cwd=source)
        print(f"[updated PR] {existing.stdout.strip()}")
    else:
        result = run(
            ["gh", "pr", "create", "--repo", "zhjnerv/ip-practice-workbench-skills",
             "--head", f"zhjnerv:{sync_branch}", "--base", branch,
             "--title", f"sync({name}): update from myskill",
             "--body", "Automated sync of the reviewed skill directory from `zhjnerv/myskill`."],
            cwd=source,
        )
        print(f"[created PR] {result.stdout.strip()}")


def main() -> int:
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("Missing IP_PRACTICE_WORKBENCH_TOKEN secret")
    entries = load_entries()
    names = changed_skills(entries)
    if not names:
        print("No changed IP practice skills.")
        return 0
    with tempfile.TemporaryDirectory(prefix="ip-practice-sync-") as temp:
        root = Path(temp)
        for name in names:
            sync_one(name, entries[name], root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"ERROR: {exc}")
