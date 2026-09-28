# 待决文件

## 原则

进入撰写之后，判断题不让流程停住。脚本采用保守默认，把问题留在 `pending_decisions`。人可以之后再改主意。只有产物本身无效或不安全时才硬阻断。

人读和人改的文件只有一份：与最终专利申请文件放在同一目录的 `待决文件.md`。审稿版 docx 里的黄底标记继续保留，二者同时存在。

## 三种载体

1. **JSON**（`pending-decisions.json`，`cn-patent-pending-decisions/v1`）
   机器汇总。刷新问题时以它为准。不要把它交给人当待决清单来改。
2. **`待决文件.md`**
   必须用 `--docx` 指向最终申请文件。脚本只把这份 Markdown 写到该 docx 的同目录，文件名固定，不能改成别的清单名。`--allow-detached` 只给测试用。
3. **正文标记** `【待决-Dnnn】`
   写在受影响的权利要求、说明书或摘要里。审稿版整段黄底；提交副本剥离标记和黄底。组装器不读 `待决文件.md`，所以改 Markdown 不会自动改 docx。

## 人怎么改

只改每条的「决定」和「标注」。不要改编号、键、位置，不要删 `<!-- item:` 边界。

- `未决`：仍按已采用默认，标记和黄底都留着。
- `采纳默认`、`维持默认`、`同意默认`、`接受默认`：认可当前稿。第二轮只删对应标记。
- `选择：` 后面的文字必须与某一条备选逐字相同。
- 其他文字，或者「决定」之外又写了「标注」：这是给第二轮的修改指示。脚本不会自己改权利要求或说明书。

再生成时按「键 + 位置」找回原编号和这两节。已经用过又消失的编号写进「已退出本轮机器清单」，不拿去标新问题。文件里已有「决定」但边界解析不了时，脚本停止覆盖。

## 第二轮

用户改完 `待决文件.md` 之后，先读决议，再改申请文件源稿，最后重装 docx：

```bash
python3 "$ROOT/scripts/run_python.py" \
  "$ROOT/skills/cn-patent-application-creator/scripts/read_pending_file.py" \
  --pending-file "<最终申请文件同目录>/待决文件.md" \
  --output "<案件目录>/待决决议.json"
```

`read_pending_file.py` 只产出 `cn-patent-pending-resolutions/v1`，法律效力是 `ADVISORY_ONLY`。它不修改四文书，也不判断技术方案对不对。

然后只处理决议里写明的条目：

- `accept_default`：源稿维持已采用默认，删掉对应 `【待决-ID】`。
- `choose` 或 `instruct`：只改该条 `target.locator` 指向的工作副本，按 `instruction` 落笔。指示含糊就保持标记，不要猜技术事实。
- `unresolved`：一个字都不要为了“干净”而改，标记和黄底留下。
- `option_unmatched`：不要当成已经选中某个备选。
- 已退出条目如果还带着标注，先确认旧标记是否还在源稿里，再决定留或删，不要把编号套到新问题上。

改完源稿后重跑受影响的验证器，再用同一个 `--docx` 重新汇总。人写过的决定和标注必须还在。然后重装审稿版和提交版。流程计划里把 `pending-round` 从 `waiting` 改为开始；改过的上游步骤用 `reopen --cascade` 打回未完成。

## 字段

- `id`：`D001` 这种编号，刷新时不重排已有条目。
- `key`：稳定机器键，去重用。
- `source`：`tool_id` 与 `rule_id`。
- `target.kind` / `target.locator`：作用位置。第二轮只改这个位置。
- `question`：要人决定的事。
- `adopted_default`：已经写进申请文件的保守做法。
- `options`：备选。
- `impact`：保护范围、授权风险、形式、交付或证据。
- `decider`：`inventor`、`attorney` 或 `both`。
