# cn-patent-fast-track-screener 任务清单

## 未完成

## 已完成

### 2026-11-04 迁移验证
- 问题：确认独立技能迁入后资源齐全、运行不依赖原工作区。
- 范围：[入口](SKILL.md)、[使用说明](README.md)、[测试](tests/test_screener.py) 和 [数据来源说明](references/data_sources.md)。
- 非目标：重新设计预审与优审规则，更新政策数据快照。
- 验收：原有脚本和数据逐文件一致，隔离运行 25 项测试通过，引用路径可达。
- 证据：在隔离副本以 `python3 -B -S -m unittest discover -s tests` 运行 25 项测试全部通过；源文件校验和及内部链接检查通过。
