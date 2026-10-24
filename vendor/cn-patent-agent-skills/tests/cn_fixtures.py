"""CN v2 审查链测试夹具：构造真实 UTF-8 申请文件并加载被测模块。

计划第 7 节允许新增窄范围 `tests/cn_*` fixture；本文件只服务 CN 审查链测试，
不影响任何非 CN 路径，也不引入第三方依赖。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MODULE_PATHS = {
    "contract": "skills/cn-patent-reviewer/scripts/cn_contract.py",
    "orchestrator": "skills/cn-patent-reviewer/scripts/build_review_bundle.py",
    "verifier": "skills/cn-patent-reviewer/scripts/verify_review_bundle.py",
    "claims": "skills/cn-patent-claims-analyzer/scripts/check_claims_cn.py",
    "specification": "skills/cn-patent-specification-reviewer/scripts/build_support_matrix_cn.py",
    "formalities": "skills/cn-patent-formalities-reviewer/scripts/check_formalities_cn.py",
}


def load_module(key: str, alias: str | None = None):
    """按路径加载被测脚本；与生产代码使用同一套加载约定。"""

    path = ROOT / MODULE_PATHS[key]
    name = alias or f"cn_fixture_{key}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CLAIMS_TEXT = (
    "1. 一种数据处理装置，其特征在于，包括控制器和存储器，所述控制器与所述存储器耦合。\n"
    "2. 根据权利要求1所述的装置，其特征在于，所述控制器执行调度算法。\n"
)

SPECIFICATION_TEXT = (
    "[0001] 技术领域\n本发明涉及数据处理领域。\n"
    "[0002] 背景技术\n现有技术中控制器与存储器之间存在延迟。\n"
    "[0003] 发明内容\n本发明提供一种数据处理装置，包括控制器和存储器。\n"
    "[0004] 具体实施方式\n所述控制器执行调度算法以降低延迟。\n"
)

FEATURES = [
    {"id": "F001", "text": "控制器"},
    {"id": "F002", "text": "存储器"},
    {"id": "F003", "text": "调度算法"},
]

PROVENANCE_FILES = {
    "search-query": "search-query.json",
    "template-candidates": "template-candidates.json",
    "template-selection": "template-selection.json",
    "stage2-gate": "stage2-gate.json",
    "feature-ledger": "feature-ledger.json",
    "claim-architecture": "claim-architecture.json",
}


def formalities_manifest() -> dict:
    """完整、可通过的形式审查 manifest；文书以真实路径引用同目录文件。"""

    return {
        "schema_version": "cn-patent-application-manifest/v2",
        "application_scope": "direct_cn_invention_application",
        "application_type": "invention",
        "filing_medium": "electronic",
        "documents": {
            "request": {"status": "provided", "content": "请求书"},
            "specification": {"status": "provided", "path": "specification.txt"},
            "claims": {"status": "provided", "path": "claims.txt"},
            "abstract": {"status": "provided", "content": "一种数据处理装置，包括控制器和存储器，用于降低访问延迟。"},
            "drawings": {"status": "confirmed_absent"},
        },
        "titles": {"request": "一种数据处理装置", "specification": "一种数据处理装置", "abstract": "一种数据处理装置"},
        "request_fields": {"applicant": "甲公司", "inventor": "张三", "address": "杭州市"},
        "execution": {"language": "zh-CN", "signature_status": "signed"},
        "abstract_figure": {"applicability": "not_applicable", "evidence": "本申请未提供附图"},
        "sequence_listing": {"applicability": "not_applicable", "evidence": "未涉及核苷酸或氨基酸序列"},
        "biological_material_deposit": {"applicability": "not_applicable", "evidence": "无需保藏生物材料"},
        "genetic_resource_statement": {"applicability": "not_applicable", "evidence": "未依赖遗传资源完成"},
        "priority_documents": {"applicability": "not_applicable", "evidence": "未主张优先权"},
        "article_24_proof": {"applicability": "not_applicable", "evidence": "未主张不丧失新颖性宽限期"},
        "divisional_documents": {"applicability": "not_applicable", "evidence": "不是分案申请"},
        "substantive_examination_request": {
            "applicability": "applicable", "status": "provided",
            "evidence": "已提出实质审查请求并缴费", "document_ids": [],
        },
    }


def write_utf8(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def write_json(path: Path, payload: object) -> None:
    write_utf8(path, json.dumps(payload, ensure_ascii=False))


def build_application(
    directory: Path,
    *,
    claims: str | None = None,
    specification: str | None = None,
    features: list | None = None,
    manifest: dict | None = None,
    provenance_artifacts: object | None = None,
    application_id: str = "CN-FIXTURE-001",
) -> Path:
    """在目录中写出一套真实 UTF-8 无 BOM 申请文件，返回 prepare 输入路径。"""

    directory.mkdir(parents=True, exist_ok=True)
    write_utf8(directory / "claims.txt", CLAIMS_TEXT if claims is None else claims)
    write_utf8(directory / "specification.txt", SPECIFICATION_TEXT if specification is None else specification)
    write_json(directory / "features.json", FEATURES if features is None else features)
    write_json(directory / "formalities-manifest.json", manifest if manifest is not None else formalities_manifest())
    if provenance_artifacts is None:
        provenance_artifacts = [
            {"artifact_id": artifact_id, "path": filename}
            for artifact_id, filename in PROVENANCE_FILES.items()
        ]
    for artifact_id, filename in PROVENANCE_FILES.items():
        write_json(directory / filename, {
            "schema_version": "cn-fixture-provenance/v1",
            "artifact_id": artifact_id,
            "application_id": application_id,
        })
    prepare_input = directory / "prepare-input.json"
    declaration = {
        "schema_version": "cn-patent-review-prepare-input/v2",
        "application_id": application_id,
        "claims": "claims.txt",
        "specification": "specification.txt",
        "features": "features.json",
        "formalities_manifest": "formalities-manifest.json",
    }
    if provenance_artifacts is not None:
        declaration["provenance_artifacts"] = provenance_artifacts
    write_json(prepare_input, declaration)
    return prepare_input


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Chain:
    """在临时工作区跑完整的 prepare -> finalize -> verify 闭环，供 E2E 与故障注入复用。"""

    def __init__(self, root: Path, **application) -> None:
        self.root = root
        self.application_directory = root / "application"
        self.workspace = root / "workspace"
        self.prepare_input = build_application(self.application_directory, **application)
        self.orchestrator = load_module("orchestrator", "cn_chain_orchestrator")
        self.verifier = load_module("verifier", "cn_chain_verifier")

    @property
    def template_path(self) -> Path:
        return self.workspace / "review-input-template.json"

    @property
    def bundle_path(self) -> Path:
        return self.workspace / "bundle.json"

    @property
    def verification_path(self) -> Path:
        return self.workspace / "verification.json"

    @property
    def summary_path(self) -> Path:
        return self.workspace / "review-summary.md"

    def raw_path(self, review_type: str) -> Path:
        return self.workspace / "raw" / f"{review_type}.json"

    def prepare(self) -> int:
        return self.orchestrator.main([
            "prepare", "--application", str(self.prepare_input), "--workspace", str(self.workspace),
        ])

    def finalize(self, review_input: Path | None = None, output: Path | None = None) -> int:
        return self.orchestrator.main([
            "finalize", "--workspace", str(self.workspace),
            "--review-input", str(review_input or self.template_path),
            "--output", str(output or self.bundle_path),
        ])

    def verify(self, bundle: Path | None = None, summary: bool = True) -> int:
        arguments = [
            "--workspace", str(self.workspace),
            "--bundle", str(bundle or self.bundle_path),
            "--output", str(self.verification_path),
        ]
        if summary:
            arguments += ["--summary", str(self.summary_path)]
        return self.verifier.main(arguments)

    def run(self) -> tuple[int, int, int]:
        return self.prepare(), self.finalize(), self.verify()

    def rewrite_json(self, path: Path, mutate) -> Path:
        """就地改写 JSON 工件，用于故障注入。"""

        payload = read_json(path)
        mutate(payload)
        path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
        return path

    def verification(self) -> dict:
        return read_json(self.verification_path)
