# 知识库文档纠错 · 技术方案

> 本文不再作为设计权威。设计用 [design-technical-rfc.md](./design-technical-rfc.md)，2026-10-14 补充见该文第 13 节。实现契约用 [spec.md](./spec.md)。

| 项 | 内容 |
|---|---|
| 关联 PRD | [prd.md](./prd.md) |
| 归属 | 积分系统 [../spec.md](../spec.md)、[../design.md](../design.md) |
| 模块 | 毕昇 `knowledge`、`approval`、`points`；客户端阅读页和审批弹窗；门户积分规则展示 |
| 错误码 | 纠错 **18400–18410**。积分调分和公司根继续用 **182**。审批沿用 18102、18103。文件不存在沿用 18020 |
| 本文地位 | 纠错表、接口、状态和 G8 发分的实现权威。金额以本文为准，不以 G8 的分值字段为准 |

## 1. 目标与取舍

**目标**：读者提交纠错，冻结上传人在现有待办里三选一。采纳并更新把新文件收成当前主版本。积分进入现有账本，规则码 G8。

**非目标**：新的审批中心、新的积分账户、按差异大小计分、完整版本管理开关、收藏通知、把文档权限扩大、改写 G1–G7。

| 决策 | 采用 | 否决 | 原因 | 何时可推翻 |
|---|---|---|---|---|
| 处理人 | 提交时写入上传人，审批前单独分支 | `ApprovalGate.submit`，以及管理员代批短路 | 申请人和处理人同一人时，现有门会自动通过；管理员短路会让非上传人处理 | 产品允许管理员代批 |
| 三个动作 | `adopt`、`adopt_update`、`reject`。旧的 `approve` 视同 `adopt` | 通用「通过」；「纠错反馈」 | 采纳不需要上传人写字；更新必须带新文件 | 产品增加第四个动作 |
| 1 分日上限 | 纠错服务按上海自然日统计已入账的采纳 | 用账本 `daily_cap` | 账本日上限会把同一天的采纳并更新也卡住 | 产品给采纳并更新也加日上限 |
| 2 分 | 每条更新写死 2，幂等键带纠错单 | 读 G8 的 `score_expr` | 管理端改一个分值无法同时表达 1 和 2 | 产品改成可配置的两档金额 |
| 新版本 | 本服务直接写版本表 | 调用完整 `KnowledgeVersionService.link_file_to_document` | 完整链路还要求版本开关、解析成功后的权限和收藏通知 | 产品要求采纳并更新同时发收藏通知或走版本开关 |
| 错误码 | 模块 184 | 继续用 182 | 182 已被积分调分、规则和公司根占用，相同数字含义不同 | 不推翻。182 保持积分专用 |

## 2. 涉及数据表

| 表 | 角色 | 结构 |
|---|---|---|
| `knowledge_file_correction` | 写纠错单 | 新表。正文只放这里 |
| `knowledge_file_correction_open` | 写待处理占位 | 新表。主键是租户、文件、反馈人 |
| `knowledge_file_correction_award` | 写每条纠错的发分结果 | 新表。`f111` 起按 `correction_id` 唯一，含 `award_kind` |
| `knowledgefile` | 读上传人和新文件状态 | 无字段变更 |
| `knowledge`、`knowledge_space_scope` | 读库和层级 | 无字段变更 |
| `user` | 读上传人是否删除 | 无字段变更 |
| `knowledge_document`、`knowledge_document_version` | 采纳并更新时写主版本 | 无字段变更 |
| `approval_instance`、`approval_task`、`approval_action_log` | 写待办 | 无字段变更。场景码 `knowledge_file_correction` |
| `point_rule` | 写 G8 展示用的分值和每日上限 | 无字段变更。G8 分值 1，`daily_cap` 空，受益人 `reporter`，状态启用 |
| `user_point_log` 及现有积分账户 | 写实际入账 | 无字段变更 |

新表每个字段带中文注释。租户条件由现有租户注入负责，业务查询不手写 `tenant_id` 过滤。`knowledge_file_correction` 模型注册进租户注入名单。

`knowledge_file_correction` 关键列：`file_id`、`knowledge_id`、`applicant_user_id`、`uploader_user_id`、`content`、`status`、`approval_instance_id`。状态为 `pending`、`approved`、`rejected`、`withdrawn`、`cancelled`。

`knowledge_file_correction_award` 关键列：`id`、`correction_id`、`award_kind`（`adopt` 或 `update`）、`award_state`（`reserved`、`awarded`、`skipped`）、`create_time`。回写入账结果时按 `correction_id` 找行，不能按「同一人同一文档」取第一行。

迁移：`v2_6_0_f110_knowledge_file_correction` 建三张表并种子 G8。`v2_6_0_f111_file_correction_award_kind` 删掉旧发分行并按纠错单重建，同时把 G8 的 `daily_cap` 置空、`score_expr` 写成固定 1 分。`f111` 的降级是空操作。

## 3. 接口与审批

| 接口 | 作用 |
|---|---|
| `POST /api/v1/knowledge/files/{file_id}/corrections` | 提交。正文必填 |
| `GET /api/v1/knowledge/file-corrections/{correction_id}` | 读正文。只有反馈人和冻结上传人 |
| `POST /api/v1/approval/tasks/{task_id}/decision` | 处理。`action` 为 `adopt`、`adopt_update` 或 `reject`。更新时带 `new_file_id` |

审批快照只存纠错单号、文件号、文档名、知识库号，不存正文。实例最终状态用已通过，不用已执行，这样现有待办仍显示已通过。纠错场景在管理员代批短路之前处理。撤回走纠错服务，再读审批详情。

删除文档的现有入口在删除成功路径上调用取消待处理纠错。只取消仍待处理的单，不改已采纳、已拒绝、已撤回。

## 4. 采纳并更新怎样改版本

新文件必须存在、属于同一知识库、解析状态为成功（数值 2）、并且不是被纠错的那一份。

原文件还没有版本时，先建逻辑文档和第一版，再把第一版降为历史，新文件成为下一主版本。新文件已经属于另一条拥有多个版本的链时，拒绝，错误码 18410。尚未解析成功时，错误码 18409，纠错单、版本和积分都不变。

这一步不检查版本管理开关，不写新的权限元组，不发收藏通知。

## 5. 发分

规则码 G8，名称「文档纠错被采纳」，受益人 `reporter`，即纠错单上的反馈人。种子分值 1，`daily_cap` 为空。这两项只供管理端展示。实际入账不读它们。

采纳先查当天是否已有 `award_kind=adopt` 且 `award_state=awarded` 的行。有则本条记 `skipped`，不投递积分。没有则记 `reserved` 并投递 1 分。

采纳并更新在新版本已成为主版本并提交纠错事务之后，记 `reserved` 并投递 2 分。

幂等键是 `earn:G8:{award_kind}:{correction_id}`。调用账本时 `daily_cap` 传空。超管、规则停用、积分关闭时动作成功，名额行记 `skipped`。投递失败时名额保持 `reserved`，同一幂等键可以再投。

自然日是 Asia/Shanghai，和积分账本一致。

## 6. 前端

纠错入口在门户嵌入的毕昇客户端，不新建门户页面。

阅读页在下载旁显示「纠错」。条件与 PRD 第 2 节相同，判断放在 `fileCorrectionAccess.ts`。弹窗只读文档名，说明最多 500 字。成功提示：已提交，可在消息中心的「申请」里查看进度。阅读页不展示历史纠错。

待办详情用纠错说明区块请求正文，不把快照里的编号铺开。18407 显示「无权查看纠错说明」。打开文档走顶层窗口 `/knowledge-spaces?spaceId=&fileId=&fileName=`。

待处理的纠错任务显示「采纳」和「采纳并更新」，隐藏通用「通过」。拒绝仍用原按钮，原因必填。采纳并更新先上传并登记文件；解析未成功时记住文件号，提示解析完成后再点一次。

门户 `pointsAdminUtils.ts` 里 G8 默认名称为「文档纠错被采纳」，受益人「反馈人」，分值 1，每日上限空。

## 7. 错误码

纠错使用模块 184。积分模块 182 的 `18201` 到 `18208` 保持原含义，见上级 [design.md](../design.md)。

| 码 | 何时 |
|---|---|
| 18400 | 说明为空 |
| 18401 | 超过 500 字 |
| 18402 | 上传人纠自己的文档 |
| 18403 | 没有可用上传人 |
| 18404 | 库层级不允许，或是收藏 |
| 18405 | 无权查看文档 |
| 18406 | 已有待处理纠错 |
| 18407 | 无权查看纠错说明 |
| 18408 | 操作人不是冻结上传人 |
| 18409 | 新文件尚未解析成功 |
| 18410 | 新文件不在同一知识库，或属于别的多版本链 |
| 18103 | 拒绝未填原因 |
| 18102 | 纠错已经处理过 |
| 18020 | 文件不存在 |

模块登记在 `features/v2.6.0/release-contract.md`。

## 8. 验证与回滚

验收走真实接口到 171 MySQL：看 HTTP 业务码，再 SELECT 纠错单、发分行、积分流水和版本主标记，然后用库里的结果再请求一次。

回滚代码后，三张纠错表和已经写入的版本、积分流水都留在库里。`f111` 不能把发分行恢复成旧的一人一文档结构。已发积分不自动追回。

## 9. 与当前代码的已知偏差

采纳的自然日用上海零点的无时区时间，和 `datetime.now()` 比较。服务器时区是东八区时与规则一致。服务器不是东八区时，当天的 1 分边界会偏。要严格按上海日切，必须改成按上海时区取当前时间再比较。

模型文件 `knowledge_file_correction.py` 顶部仍写着「第一次通过的积分名额」。这句和最终规则不符，应改成「一条纠错一次发分」。本文落盘时没有改这句注释。
