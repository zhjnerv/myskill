# 中国发明专利审查基准案例（CN v2）

所有案例均为虚构材料。预期状态按 [cn-review-contract-v2.json](cn-review-contract-v2.json) 判断。

## 直接申请的完整输入

权利要求、说明书、摘要、请求书、附图说明和三个原始报告均以当前 UTF-8 无 BOM 字节绑定。预期：所有 41 个维度出现；条件性维度有充分 `NOT_APPLICABLE` 证据或明确 gap；输出仅为 `ADVISORY_ONLY`。

## PCT 国家阶段输入

输入声明 PCT 国家阶段。预期：直接申请范围拒绝或转入后续模块；不得用本规范的直接申请请求书程序得出结论。

## 原始 finding 重放或丢失

在 finalize 前删除、复制或降低任一原始 `DETERMINISTIC_FAIL`/`REVIEW_REQUIRED`。预期：独立 verifier 报契约错误；不得用新的概括性 finding 取代其稳定 ID。

## 仅有 v1 检索 manifest

manifest 字段与哈希均有效，但没有单一方案全文、有效日或专业技术证据。预期：`novelty` 与 `inventiveness` 为 `INCONCLUSIVE` 或覆盖不完整，绝不能据此声称授权、通过或可申报。

## 资源越限

权利要求超过 4 MiB、JSON 深度超过 64、finding 超过 5,000，或编排超过 180 秒。预期：工具错误退出码 `4`，不写部分法律 finding。
