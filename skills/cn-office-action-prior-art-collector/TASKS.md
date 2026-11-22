# cn-office-action-prior-art-collector 任务清单

## 未完成

## 已完成

### 独立仓库的 Windows 验收
- 在 Python 3.12 下将 [自测](scripts/selftest.py) 的路径断言改为 Path 对象比较，23 项通过。
- [DOCX 评测附件](evals/files/second_oa_scooter.docx) 实际解析出 4 篇第 5 栏文献和 3 条正文审查意见，忽略检索报告。
- 业务脚本和数据未改，实际联网下载未测试。

### 2026-11-04 迁移验证
- 问题：确认独立技能迁入后可以解析材料、规范化号码并生成取材演练结果。
- 范围：[入口](SKILL.md)、[使用说明](README.md)、[自测](scripts/selftest.py) 和 [评测用例](evals/evals.json)。
- 非目标：撰写审查意见答复，调用网络进行批量文献下载。
- 验收：原有文件逐文件一致，隔离运行 23 项自测通过，评测附件和引用路径可达。
- 证据：在隔离副本以 `python3 -B -S scripts/selftest.py` 运行 23 项自测全部通过；源文件校验和、评测附件相对路径及内部链接检查通过。联网取材未实测。
