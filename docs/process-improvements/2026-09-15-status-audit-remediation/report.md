# 项目状态审计修复报告

- 对照报告：`/tmp/cn-patent-status-audit-20260915/project-status-report.md`
- 范围：当前工作区，不包含客户案件、真实 CODEX_HOME、发布、提交或推送。
- 结论：审计报告中的 F01—F11 已完成代码修复并通过当前机器检查；这不是法律内容签署、视觉验收或跨平台安装签署。

## 1. 11 项问题处理结果

| 编号 | 结果 | 处理摘要 | 主要验证 |
|---|---|---|---|
| F01 | 已修复 | 新增 `cn_drafting_io.py`；输入、输出、`--table` 做规范化路径、`samefile`、硬链接和符号链接别名检查；暂存、`fsync`、替换前复检，避免报告覆盖原文。 | 起草安全定向测试；`reproduce_core.py` 同路径/硬链接/符号链接均 exit 3，源文件未变 |
| F02 | 已修复 | 交付器重新调用当前 `verify_docx_assembly`；当前 DOCX、组装输入、PNG、Draw.io 均按字节复算；报告相对路径按报告目录解析；每幅图强制 `final_png` 和 `drawio` 双绑定。 | 真实组装、替换 `word/media/*.png`、替换 XML、删除、整体替换；独立编号/路径边界 17 项通过 |
| F03 | 已修复 | 范例只提供视觉/几何样式，箭头端、source/target、原生关系标签由母版保留；验证器拒绝反向、无目标端、双向箭头。 | 附图语义反例重放 |
| F04 | 已修复 | v4 `decision_bindings` 逐项绑定 true/false 的关系 ID、目标步骤和原生标签；拒绝真假交换、目标交换、缺支和额外出支。 | v4 合同及决策极性反例 |
| F05 | 已修复 | 节点文字经合法 HTML/换行/空白规范化后完整比较；部件标记须显式登记，不再用任意子串放行。 | “禁止执行”后缀、缺字、偷换字反例 |
| F06 | 已修复 | 引用区间完整展开，受 `MAX_REFERENCE_EDGES` 资源预算约束；超预算明确失败，不再静默只保留端点。 | `1至501`、`1至502`、`1至601` 均检出中间多项从属 |
| F07 | 已修复 | 安全重建保留 `ellipse;`、`rhombus;` 等无等号命名形状，并增加不变输入幂等回归。 | 命名形状反例重放 |
| F08 | 已修复 | 步骤编号按模板真实层级选择；最终 DOCX 独立读取 `document.xml`/`numbering.xml`；损坏/缺失编号、非法层级、裸 `lvlOverride` fail-closed；`numId=0`按取消编号处理。 | 编号/路径独立测试 17 passed；DOCX 定向 63 passed、1 skipped |
| F09 | 已修复 | 安装日志先写 `prepared`，启动自动恢复未提交事务；SIGTERM 先回滚再恢复原信号语义；SIGKILL 留可恢复日志。 | 安装交叉验收：中断恢复、幂等清理 |
| F10 | 已修复 | runtime 与七个 Skill 入口共用事务备份/回滚；copy fallback 的入口内容和 symlink 形态一起恢复；`committed` 清理中断不回滚新版本。 | 混合 symlink/copy、manifest 失败和清理中断反例 |
| F11 | 已修复 | 安装器和包验证器共用 `collect_source_files`；各层 `.local-case-archive`、`archive`、临时目录和未经审核二进制产物阻断，不依赖 `.gitignore`。 | 安装安全预期重放 PASS；包边界 PASS |

## 2. 误报裁决

以下结论没有作为缺陷修复，保留原审计的裁决：

- `run_python.py` 已对路径 `resolve()` 后做根目录约束，不构成沙箱逃逸。
- 安装中断时旧 runtime 备份仍完整；真实缺陷是运行窗口不可用和 copy fallback 混版，不是旧数据丢失。
- 包版本 `0.2.0` 与附图 Skill 版本 `4.7.0` 属于不同版本层级，不要求同号。
- `docs/process-improvements/` 不进入运行时白名单与 `.gitignore` 是不同治理边界，不构成冲突。
- nested `archive` 的原报告解释不准确；真实缺口是未经审核 PDF/本地产物可进入分发白名单。
- 循环引用、P000x 段落定位、字节/行数资源限制、守恒计数均未证明原报告所说的灾难性缺陷。

## 3. 复现与验证路径

审计原始报告和反例：

- `/tmp/cn-patent-status-audit-20260915/project-status-report.md`
- `/tmp/cn-patent-status-audit-20260915/pm-core/reproduce_core.py`
- `/tmp/cn-patent-status-audit-20260915/codex-diagrams/probe_real_docx.py`
- `/tmp/cn-patent-status-audit-20260915/codex-package-review/repro_package_review.py`

本轮收口证据：

- `/tmp/cn-patent-status-audit-20260915/remediation-final/pytest-final.log`
- `/tmp/cn-patent-status-audit-20260915/remediation-final/verify-package.json`
- `/tmp/cn-patent-status-audit-20260915/remediation-final/harness.json`
- `/tmp/cn-patent-status-audit-20260915/remediation-final/security.json`
- `/tmp/cn-patent-status-audit-20260915/remediation-final/installer-cross-acceptance.md`
- `/tmp/cn-patent-audit-fixes-20260916/independent-docx/verification-summary.md`
- `/tmp/cn-patent-audit-fixes-20260916/pm-replay/pm-core-final-r2/results.json`
- `/tmp/cn-patent-audit-fixes-20260916/pm-replay/codex-diagrams/real-docx-probe-final/summary.json`
- `/tmp/cn-patent-audit-fixes-20260916/pm-replay/codex-package-review/run-wwxqb48z/results.json`

最终验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
# 结果：356 passed, 1 skipped, 107 subtests passed

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B scripts/verify_package.py
# 结果：PASS

python3 <skill-lint>/scripts/harness_failure_audit.py batch --root skills
# 结果：PASS，7 个 Skill，0 findings

python3 <skill-lint>/scripts/security_scan.py batch --root skills
# 结果：WARN，0 critical/high；12 个既有 medium/low 能力提示
```

## 4. 尚未声称的事项

- 默认视觉测试未执行；1 个 LibreOffice/PDF 合成渲染测试保持 skip，只有设置 `CN_PATENT_RUN_VISUAL_TESTS=1` 才运行。
- 未进行人工 Word/PNG 逐页视觉验收。
- 未在 Windows `msvcrt` 分支或跨文件系统 rename 环境运行安装器。
- 未进行真实用户 `CODEX_HOME` 安装，也未执行发布、提交、推送或全局环境写入。
- Skill Stability `assess` 仍是 `NOT_VERIFIED`：本轮不把普通 pytest 和静态 PASS 伪装成候选外三轮稳定性签名证据。
- 当前工作区仍保留用户在任务开始前已有的修改和新文件；详见收口 `final-integrity.json`，没有擅自清理。
