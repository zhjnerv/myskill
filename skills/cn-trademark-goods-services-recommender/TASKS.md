# cn-trademark-goods-services-recommender 任务清单

## 未完成

## 已完成

### 2026-11-04 迁移验证
- 问题：确认独立技能迁入后离线数据完整，选类校验和申报表导出可运行。
- 范围：[入口](SKILL.md)、[使用说明](README.md)、[测试](tests/test_recommender.py)、[数据清单](data/manifest.json) 和 [导出规范](references/export_template_spec.md)。
- 非目标：调整推荐方法，更新区分表快照或公开再分发数据。
- 验收：原有脚本、模板、测试和评测用例逐文件一致；数据仅统一为 LF 行尾，JSON 内容不变；隔离运行 25 项测试、数据完整性及引用检查通过。
- 证据：545 份数据 JSON 与源文件逐一比较，差异仅为 CRLF 转 LF，结构化内容一致。调整后在隔离副本以 `python3 -B -S -m unittest discover -s tests` 复跑 25 项测试全部通过；`scripts/build_data.py --validate-only` 核对 45 大类、498 类似群、31,749 商品服务项和 1,006 条注释。README 仅将过时的维护文件清单改为三份实际账本。
