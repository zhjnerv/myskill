#!/usr/bin/env python3
"""
风格分析器测试脚本
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# 模拟的权利要求书
MOCK_CLAIMS = """1. 一种分布式锁管理系统，其特征在于，包括：
   协调服务器，用于接收锁请求并分配锁资源；
   客户端节点，用于向所述协调服务器发送锁请求；
   持久化存储，用于保存锁状态信息。

2. 根据权利要求1所述的分布式锁管理系统，其特征在于，所述协调服务器采用多副本架构。

3. 根据权利要求2所述的分布式锁管理系统，其特征在于，所述多副本架构使用Raft一致性协议。

4. 根据权利要求1所述的分布式锁管理系统，其特征在于，所述客户端节点包括重试机制。

5. 根据权利要求1所述的分布式锁管理系统，其特征在于，所述持久化存储采用RocksDB实现。
"""

# 模拟的说明书
MOCK_SPEC = """# 分布式锁管理系统

## 技术领域

本发明涉及分布式计算技术领域，具体涉及一种分布式锁管理系统及其实现方法。

## 背景技术

现有的分布式锁系统存在单点故障和性能瓶颈问题。传统的集中式锁服务器无法满足高并发场景下的需求，而且在服务器故障时会导致整个系统无法工作。

## 发明内容

本发明提供一种分布式锁管理系统，通过采用多副本架构和一致性协议，解决了现有技术的上述问题。该系统能够在保证数据一致性的前提下，提高系统的可用性和吞吐量。

## 附图说明

图1是本发明分布式锁管理系统的整体架构示意图。

图2是本发明协调服务器的内部结构示意图。

图3是本发明系统中锁获取流程的时序图。

图中：100-协调服务器、110-锁管理模块、120-副本同步模块、200-客户端节点、210-锁请求队列、300-持久化存储。

## 具体实施方式

### 实施例1

如图1所示，本发明提供一种分布式锁管理系统，包括协调服务器100、客户端节点200和持久化存储300。

协调服务器100用于接收来自客户端节点200的锁请求并分配锁资源。在一个具体实施方式中，协调服务器100采用多副本架构，提高系统可用性。

锁管理模块110负责维护锁的状态，包括已分配、已释放等状态。副本同步模块120负责在多个副本之间同步锁状态信息，确保数据一致性。

### 实施例2

在另一实施例中，协调服务器100使用Raft一致性协议实现副本同步。Raft协议是一种易于理解的一致性算法，通过选举机制和日志复制保证分布式系统中数据的一致性。

客户端节点200首先向协调服务器100发送锁请求。锁请求包括锁的标识符、锁的类型（读锁或写锁）和超时时间等信息。

### 实施例3

在又一实施例中，客户端节点200包括重试机制。当锁请求失败或超时时，客户端会自动重试，直到成功获得锁或达到最大重试次数。

持久化存储300采用RocksDB实现，提供高效的键值存储能力。系统通过定期将锁状态写入持久化存储，保证即使在节点故障后也能恢复系统状态。
"""

# 模拟的摘要
MOCK_ABSTRACT = """本发明提供一种分布式锁管理系统，包括协调服务器、客户端节点和持久化存储。协调服务器采用多副本架构，使用Raft一致性协议实现副本同步，提高系统可用性。客户端节点包括重试机制，提高锁获取的成功率。持久化存储采用RocksDB实现。该系统通过多副本和一致性协议解决了单点故障和性能瓶颈问题。"""


def test_style_analyzer():
    """测试风格分析器"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # 写入模拟文件
        claims_file = tmpdir / "claims.txt"
        spec_file = tmpdir / "spec.txt"
        abstract_file = tmpdir / "abstract.txt"
        output_file = tmpdir / "style-guide.json"

        claims_file.write_text(MOCK_CLAIMS, encoding="utf-8")
        spec_file.write_text(MOCK_SPEC, encoding="utf-8")
        abstract_file.write_text(MOCK_ABSTRACT, encoding="utf-8")

        # 运行分析器
        script = Path(__file__).resolve().parents[1] / "skills" / "cn-patent-application-creator" / "scripts" / "analyze_template_style.py"

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--patent-number",
                "CN202010123456.X",
                "--claims",
                str(claims_file),
                "--specification",
                str(spec_file),
                "--abstract",
                str(abstract_file),
                "--output",
                str(output_file),
            ],
            capture_output=True,
            text=True,
        )

        print("=== 标准输出 ===")
        print(result.stdout)

        if result.returncode != 0:
            print("=== 标准错误 ===")
            print(result.stderr)
            return False

        # 验证输出
        try:
            style_guide = json.loads(output_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"错误：JSON 解析失败：{e}")
            return False

        print("\n=== Style Guide Summary ===")
        print("Schema ID: {}".format(style_guide['schema_id']))
        print("Template Patent: {}".format(style_guide['template_patent']))
        print("Claims Style:")
        print("  - Independent claims: {} items".format(
            style_guide['claims_style']['independent_claims_count']
        ))
        print("  - Dependent claims: {} items".format(
            style_guide['claims_style']['dependent_claims_count']
        ))
        print("  - Dependency pattern: {}".format(style_guide['claims_style']['dependency_pattern']))

        print("\nSpecification Style:")
        print("  - Embodiments: {} examples".format(style_guide['specification_style']['embodiments_count']))
        print("  - Description mode: {}".format(style_guide['specification_style']['description_mode']))
        print("  - Avg paragraph length: {} chars".format(
            style_guide['specification_style']['avg_paragraph_chars']
        ))

        print("\nDrawing Style:")
        print("  - Total drawings: {} figures".format(style_guide['drawing_style']['total_drawings']))
        print("  - Reference signs: {} marks".format(style_guide['drawing_style']['reference_sign_count']))
        print("  - Drawing types: {}".format(", ".join(style_guide['drawing_style']['drawing_types'])))

        if style_guide.get("abstract_style"):
            print("\nAbstract Style:")
            print("  - Characters: {}".format(style_guide['abstract_style']['chars_count']))
            print("  - Structure pattern: {}".format(style_guide['abstract_style']['structure_pattern']))

        print("\n=== Verification ===")
        checks = [
            (
                style_guide["template_patent"] == "CN202010123456.X",
                "Template patent number is correct",
            ),
            (
                style_guide["claims_style"]["independent_claims_count"] == 1,
                "Independent claims count is correct",
            ),
            (
                style_guide["claims_style"]["dependent_claims_count"] == 4,
                "Dependent claims count is correct",
            ),
            (
                style_guide["specification_style"]["embodiments_count"] == 3,
                "Embodiments count is correct",
            ),
            (
                style_guide["drawing_style"]["total_drawings"] == 3,
                "Drawing count is correct",
            ),
            (
                "schema_id" in style_guide and "template_patent" in style_guide,
                "Required fields are present",
            ),
            (
                style_guide["extraction_methodology"]["confidence_level"] in ["high", "medium", "low"],
                "Confidence level field is valid",
            ),
        ]

        all_passed = True
        for check, description in checks:
            status = "[PASS]" if check else "[FAIL]"
            print(f"{status} {description}")
            if not check:
                all_passed = False

        if all_passed:
            print("\n[PASS] All tests passed")
            return True
        else:
            print("\n[FAIL] Some tests failed")
            return False


if __name__ == "__main__":
    success = test_style_analyzer()
    sys.exit(0 if success else 1)
