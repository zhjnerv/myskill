# qu-ai-wei 本地账

## 2026-11-02 平均断句长度

- 问题：连续碎句使正文节奏机械；既有 [需求](qu-ai-wei-average-segment-length.md) 要求普通正文平均片段字数 >=10。
- 范围：[SKILL.md](../../skills/qu-ai-wei/SKILL.md) 的重写与复扫步骤；新增 [统计脚本](../../skills/qu-ai-wei/scripts/segment_length.py) 和 [计数测试](../../skills/qu-ai-wei/tests/test_segment_length.py)。
- 非目标：不新增事实、不改变声口或受保护文字；不要求每句等长，不修改上游版本、账本和 registry 同步基线。
- 改动：五种断句标点、段末片段、排除范围、按全文片段加权计算及不适用情形均明确；脚本仅对已筛选的 UTF-8 纯文本计数，不自动判断保护边界。
- 证据：8 项计数/CLI 测试通过，skill-creator `quick_validate` 通过。skill-lint 静态安全扫描没有 high/critical；命中均为原有测试文件中的 `eval` 字样或本次测试的固定参数子进程调用，已核实未新增运行时命令执行、外联或写文件行为。
- 遗留：模型的全文改写质量和多轮遵循稳定性不由计数通过保证。
- 回退：撤回本次 SKILL.md 段落及新增脚本/测试；安装副本保留修改前备份。
