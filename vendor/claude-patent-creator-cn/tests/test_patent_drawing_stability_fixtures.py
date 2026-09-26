import json
import subprocess
from pathlib import Path

SKILL_DIR = Path("skills/cn-patent-diagram-generator")
CONTRACT_PATH = SKILL_DIR / "config" / "instruction-stability-contract.json"
CHECKER_SCRIPT = SKILL_DIR / "scripts" / "check_stability_evidence.py"

def test_stability_fixtures():
    contract = json.loads(CONTRACT_PATH.read_text("utf-8"))
    cases = contract.get("cases", [])
    checkers = {c["id"]: c for c in contract.get("checkers", [])}

    for case in cases:
        for checker_id in case.get("checker_ids", []):
            checker = checkers[checker_id]

            # Map artifact IDs to paths for this case
            artifacts = case.get("artifacts", [])
            artifact_paths = {a["artifact_id"]: SKILL_DIR / a["path"] for a in artifacts}

            # Expand args
            args = []
            for arg in checker.get("args", []):
                if arg.startswith("{artifact:") and arg.endswith("}"):
                    artifact_id = arg[10:-1]
                    args.append(str(artifact_paths[artifact_id]))
                else:
                    args.append(arg)

            # Run check
            cmd = ["python3", str(CHECKER_SCRIPT)] + args
            result = subprocess.run(cmd, capture_output=True, text=True)
            assert result.returncode == case.get("expected_exit_code", 0), f"Case {case['id']} with checker {checker_id} failed. Output: {result.stdout} {result.stderr}"

def test_v4_positive_fixture_content():
    v4_path = SKILL_DIR / "assets/stability/positive-final-verification-v4.json"
    content = v4_path.read_text("utf-8")
    data = json.loads(content)

    assert data.get("schema_id") == "cn-patent-drawing-verification/v4", "Schema ID must be v4"
    assert "DDS" not in content, "Must not contain real customer terms like DDS"
    assert "啁啾" not in content, "Must not contain real customer terms like 啁啾"
