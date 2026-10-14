# SPEC: 知识库文档纠错

> Technical specification derived from: [prd.md](./prd.md)
> Generated: 2026-10-13 | Target branch: `feat-2.5.0-sg-lkk-1010` | Commit: `d2c3ae1b7`（纠错实现在该提交之后的未提交工作区）

设计取舍、失败停点和 `f111` 迁移以 [design-technical-rfc.md](./design-technical-rfc.md) 为准。本文只写实现契约。不重复那份 RFC 里的候选方案。

## 1. Summary

### 1.1 What This SPEC Covers

毕昇客户端提交文档纠错，冻结上传人在现有审批待办里采纳、采纳并更新或拒绝。采纳并更新把新文件收成当前主版本。积分进入现有账本，规则码 G8。门户只改 G8 的展示默认值。

### 1.2 PRD Reference

- Source: [prd.md](./prd.md)
- 覆盖：PRD 第 2–6 节的角色、三动作、积分和审批
- 验收：AC-01 至 AC-18

### 1.3 Design Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| 设计权威 | [design-technical-rfc.md](./design-technical-rfc.md) 方案 A | 2026-10-13 保留该文档，不另写一份取舍 |
| 决策入口 | 现有 `POST /api/v1/approval/tasks/{task_id}/decision` | 不新建审批产品 |
| 金额 | 事件内 1 或 2，账本 `daily_cap` 传空；更新另按人按日最高 10 分 | 见 RFC 第 6、13 节 |
| 错误码 | 18400–18410 | 182 已被积分占用 |
| 响应包络 | 现有 `status_code` / `status_message` / `data` | 不新定义一套 HTTP 状态语义 |

## 2. Architecture

### 2.1 System Context

门户页面嵌入毕昇客户端。纠错请求直接到毕昇 `/api/v1`。门户 BFF 不实现纠错规则。积分管理页只读 G8 的名称、分值 1 和空的每日上限。

### 2.2 Component Design

| 模块 | 职责 | 不负责 |
|---|---|---|
| `KnowledgeFileCorrectionService` | 资格、状态、版本主标记、发分行 | 积分流水的账户锁 |
| `ApprovalCenterService.decide_task` | 在管理员短路之前把纠错任务交给纠错服务 | 纠错正文 |
| `PointsAwardFacade.on_file_correction_adopted` | 事务提交后的 G8 入账 | 把纠错从已采纳打回待处理 |
| 客户端阅读页和待办 | 展示和收集输入 | 授权 |

### 2.3 Module Interactions

提交在一个数据库事务里写纠错单、审批实例、审批任务和待处理占位。采纳并更新登记时只写 `pending_update_file_id`，纠错仍 `pending`。解析成功后的事务里改版本、把纠错标成 `approved`、按当天剩余额度插入 `reserved` 或 `skipped` 发分行，然后提交。积分门面在提交之后调用。失败时纠错停在哪，以 RFC 第 8、13 节为准。

### 2.4 File Structure

```
src/backend/bisheng/
├── common/errcode/file_correction.py                         18400–18410
├── knowledge/api/endpoints/knowledge_file_correction.py      提交和读正文
├── knowledge/domain/models/knowledge_file_correction.py      三张表
├── knowledge/domain/services/knowledge_file_correction_service.py
├── approval/api/endpoints/approval_user.py                   decision 增加 new_file_id
├── approval/domain/services/approval_center_service.py       纠错分支在管理员短路之前
├── points/domain/services/points_award_facade.py             G8 事件
├── points/domain/services/points_award_hooks.py              投递和回写发分行
└── core/database/alembic/versions/
    ├── v2_6_0_f110_knowledge_file_correction.py
    └── v2_6_0_f111_file_correction_award_kind.py

src/frontend/client/src/
├── api/fileCorrection.ts
├── api/approval.ts                                           adopt / adopt_update
├── pages/knowledge/portal/fileCorrectionAccess.ts
├── pages/knowledge/portal/components/FileCorrectionDialog.tsx
└── components/approval/
    ├── FileCorrectionNotice.tsx
    ├── FileCorrectionDecision.tsx
    └── ApprovalCenterDialog.tsx

门户 frontend/src/pages/admin/pointsAdminUtils.ts             只改 G8 展示默认值
```

## 3. Data Model

物理列和中文注释以 RFC 第 7 节的三张表为准。这里只固定实现必须遵守的键和枚举。

| 表 | 键 | 枚举 |
|---|---|---|
| `knowledge_file_correction` | 主键 `id` | `status`: `pending` `approved` `rejected` `withdrawn` `cancelled` |
| `knowledge_file_correction_open` | 主键 `tenant_id + file_id + applicant_user_id` | 仅待处理期间存在 |
| `knowledge_file_correction_award` | 唯一 `correction_id` | `award_kind`: `adopt` `update`。`award_state`: `reserved` `awarded` `skipped` |

审批快照只存 `correction_id`、`file_id`、`file_name`、`space_id`。不存 `content`。

`point_rule` 中 G8：`rule_code=G8`，名称「文档纠错被采纳」，`beneficiary=reporter`，`score_expr` 固定 1 分，`daily_cap` 为空，`status=enabled`。实发不读 `score_expr`。

迁移顺序：`f110` 建表并种子 G8，`f111` 删除发分行后按 `correction_id` 重建。`f111` 降级为空操作。执行条件见 RFC 第 9 节。

## 4. API Design

前缀 `/api/v1`。身份为登录用户。成功时 `status_code` 为 200，业务体在 `data`。

### 4.1 Endpoints

| Method | Path | Description | Auth | Request | Response `data` |
|---|---|---|---|---|---|
| POST | `/knowledge/files/{file_id}/corrections` | 提交 | 登录 | `{ "content": string }` | `correction_id` `instance_id` `task_id` `status=pending` |
| GET | `/knowledge/file-corrections/{correction_id}` | 读正文 | 登录，且是反馈人或冻结上传人 | 无 | `correction_id` `file_id` `file_name` `space_id` `content` `status` `applicant_user_id` `uploader_user_id` `pending_update_file_id` `update_file_status` `update_phase` |
| POST | `/knowledge/file-corrections/{correction_id}/retry-update-file` | 失败文件重新解析 | 登录冻结上传人 | 无 | `id` `status` `file_name` `update_phase` |
| POST | `/approval/tasks/{task_id}/decision` | 处理 | 登录，且是该任务冻结上传人 | 见 4.2 | 现有决策结果：`task_id` `instance_id` `status` `instance_status` `comment` |
| POST | `/approval/instances/{instance_id}/withdraw` | 撤回 | 登录反馈人，且仍为 pending | 现有撤回体，`reason` 可空 | 现有撤回结果 |

删除文档不新增接口。现有删除成功路径调用取消待处理纠错。

### 4.2 Request/Response Schemas

决策请求：

```json
{ "action": "adopt", "comment": null, "new_file_id": null }
```

| 字段 | 类型 | 规则 |
|---|---|---|
| action | string | 纠错任务接受 `adopt`、`adopt_update`、`reject`。`approve` 视同 `adopt`。其他值按已处理拒绝，码 18102 |
| comment | string 或空 | 拒绝时去空白后必须非空。采纳和采纳并更新不要求 |
| new_file_id | int 或空 | 仅 `adopt_update` 必填 |

`content` 去首尾空白后按 Python `len` 计，1 到 500。待办展示标题为 `纠错：` 加文档名快照。

### 4.3 Error Responses

见第 6 节。失败响应不带纠错正文，也不把无权说成文件不存在。

### 4.4 Breaking Changes

决策接口只增加可选字段 `new_file_id` 和两个动作值。非纠错任务的 `approve` / `reject` 不变。新路径对旧客户端不存在。只升级服务、不升级客户端时，纠错待办上的旧「通过」会变成采纳，不会变成采纳并更新。

## 5. Business Logic

### 5.1 Core Algorithms

提交，全部通过才插入：

1. 文件在当前租户可见，否则 18020。
2. `view_file` 允许，否则 18405。
3. 库不是收藏，层级是 `public`、`department`、`team` 或 `team_ks`，否则 18404。
4. 说明长度合法，否则 18400 或 18401。
5. 当前用户不是 `knowledgefile.user_id`，否则 18402。
6. 上传人存在且 `user.delete` 不是 1，否则 18403。
7. 占位主键不冲突，否则 18406。

采纳：版本不动。若当天没有 `award_kind=adopt` 且 `award_state=awarded` 的发分行，则 `reserved` 并在提交后投递 `delta=1`。已有则发分行直接 `skipped`，不投递。

采纳并更新登记：写入指针，不关单。指针文件仍在解析时，其他动作 18411。解析成功后写主版本；当天该反馈人 `award_kind=update` 且 `reserved`/`awarded` 的分数加 2 不超过 10 则投递 `delta=2`，否则发分行 `skipped`。旧决策在新文件已是 `status=2` 时可当场关单，同样走 10 分封顶。

拒绝：原因为空则 18103，不写终态。通过后 `rejected`，不写发分行。

撤回和删除只处理 `pending`。删除不修改已 `approved` 的纠错，不删除已有积分流水。

### 5.2 Validation Rules

- 库层级看不清时，客户端隐藏按钮。服务端仍执行第 5.1 节。
- 新文件属于另一条已有多个版本的链时，18410。
- 幂等键 `earn:G8:{award_kind}:{correction_id}`。重复投递不加第二笔。
- 发分行回写按 `correction_id`。

### 5.3 State Machine

状态和非法边以 RFC 第 7 节的状态图为准。终态不能回到 `pending`。

### 5.4 Edge Cases

| 情况 | 结果 |
|---|---|
| 同一天先采纳再采纳并更新 | 1 分和 2 分都入账 |
| 同一天两次采纳 | 第二次已采纳，发分 `skipped`，流水合计仍为 1 |
| 积分开关关闭、G8 停用或反馈人是平台超管 | 纠错已采纳或已更新，发分 `skipped` |
| 积分投递抛错 | 纠错保持已采纳，发分保持 `reserved`。见 RFC 第 8 节 |
| 站内信失败 | 流水已提交则分数仍在 |
| 服务器不是东八区 | 采纳日切可能偏离上海零点。发布前按 RFC 第 11 节验证 |

## 6. Error Handling

### 6.1 Error Taxonomy

业务码放在统一响应的 `status_code`。文案为 `status_message`。

| Code | Condition | User Message |
|---|---|---|
| 18400 | 说明为空 | 请填写纠错说明 |
| 18401 | 超过 500 字 | 纠错说明不能超过 500 字 |
| 18402 | 上传人提交自己的文档 | 不能为自己上传的文档提交纠错 |
| 18403 | 没有可用上传人 | 当前没有可处理的上传人 |
| 18404 | 库层级不允许或是收藏 | 当前文档不能提交纠错 |
| 18405 | 无权查看文档 | 无权查看该文档 |
| 18406 | 已有待处理纠错 | 你已有一条审批中的纠错, 请在「申请」中查看 |
| 18407 | 无权看正文，或纠错单不存在 | 无权查看纠错说明 |
| 18408 | 操作人不是冻结上传人 | 只有文档上传人可以处理这条纠错 |
| 18409 | 新文件未解析成功 | 新文件还在解析, 解析完成后再采纳并更新 |
| 18410 | 新文件不能成为这一篇的新版本 | 请上传同一知识库中的另一份新文件 |
| 18411 | 更新文件仍在解析 | 新文件正在解析, 请等待完成后再处理 |
| 18412 | 没有失败的更新文件却重解析 | 当前没有解析失败的更新文件, 无法重新解析 |
| 18103 | 拒绝未填原因 | 沿用审批模块现有文案 |
| 18102 | 纠错已处理，或动作无法识别 | 沿用审批模块现有文案 |
| 18020 | 文件不存在 | 沿用知识库现有文案 |

### 6.2 Retry Strategy

积分投递失败不自动把纠错打回待处理。同一幂等键可以再投。Celery 任务 `process_points_award_event` 没有失败后的自动重试配置。队列确认过的失败不会自己再来。

客户端在登记成功后按 `update_phase` 显示更新中, 并轮询 GET 纠错. 不要把登记成功当成已关单.

### 6.3 Failure Modes

依赖失败时的数据停点以 RFC 第 8 节的表为准。SPEC 不另写一套。

## 7. Security

### 7.1 Authentication & Authorization

提交的查看权使用 `PermissionService.check` 的 `view_file`。决策权只比较任务审批人和纠错单上的 `uploader_user_id`。平台管理员没有例外。读正文只允许 `applicant_user_id` 或 `uploader_user_id`。记录不存在也返回 18407。

### 7.2 Input Validation

`content` 最长 500 个字符。拒绝原因沿用审批字段上限。不接收附件。

### 7.3 Data Protection

正文只在 `knowledge_file_correction.content`。审批动作日志可带纠错单号，不带正文。不新增加密和保留期限。

## 8. Performance

### 8.1 Expected Load

没有 QPS 承诺。假设纠错次数远小于文件上传。

### 8.2 Optimization Strategy

不新增缓存。待办列表沿用审批查询。

### 8.3 Database Considerations

占位主键保证一人一文档一条待处理。发分行唯一约束保证一条纠错一次发分结果。采纳日切查询使用 `tenant_id, file_id, applicant_user_id, award_kind, create_time` 这一组索引。

## 9. Testing Strategy

写路径测试走真实接口到 171 MySQL，断言业务码，再 SELECT，再请求一次。文件是 `src/backend/test/knowledge/test_file_correction_flow.py`。不写入知识库巨石测试。达梦未跑，不把 171 的结果写成达梦已通过。

### 9.1 Unit Tests

客户端按钮条件：`fileCorrectionAccess.test.ts`。只覆盖显示和隐藏，不覆盖入账。

### 9.2 Integration Tests

`test_file_correction_flow.py` 覆盖提交、重复、拒绝、撤回、管理员代批、并发、同日采纳上限、两次采纳并更新。

### 9.3 Edge Case Tests

未解析文件保持 `pending`。投递失败保持 `approved` 加 `reserved`。生产库执行 `f111` 前数发分行。后两条在现有测试里没有单独用例，发布前按 RFC 第 10、11 节补。

### 9.4 Acceptance Criteria Mapping

| AC | Test | Type | Description |
|---|---|---|---|
| AC-01 | `test_submit_approve_points_and_second_pass_mysql` | integration | 提交成功且待办可列出 |
| AC-02 | `test_submit_rejections_mysql` | integration | 18402，无脏行 |
| AC-03 | 同上 | integration | 18403 |
| AC-04 | 同上 | integration | 18404 与 18405 |
| AC-05 | 同上 | integration | 18400 与 18401 |
| AC-06 | 同上，以及 `test_concurrent_submit_mysql` | integration | 18406，pending 一行 |
| AC-07 | `test_submit_approve_points_and_second_pass_mysql` | integration | 采纳后流水为 1 |
| AC-08 | 同上，以及 `test_cap_super_admin_rule_disabled_and_cancel_mysql` | integration | 同日第二次采纳合计仍为 1 |
| AC-09 | `test_adopt_update_pays_each_new_version_mysql` | integration | 新文件为主版本，旧文件不是 |
| AC-10 | 同上 | integration | 两笔合计 4，且两行 `update/awarded` |
| AC-11 | 无单独用例 | integration | 发布前补 18409 且行数不变 |
| AC-12 | `test_reject_withdraw_admin_and_levels_mysql` | integration | 18103 |
| AC-13 | 同上 | integration | 拒绝后无积分流水 |
| AC-14 | 同上 | integration | 18408 |
| AC-15 | 同上 | integration | 撤回后可再提交 |
| AC-16 | `test_cap_super_admin_rule_disabled_and_cancel_mysql` | integration | 待处理变为 cancelled |
| AC-17 | `test_submit_rejections_mysql` | integration | 18407 |
| AC-18 | `test_cap_super_admin_rule_disabled_and_cancel_mysql` | integration | 超管与规则停用为 skipped |

## 10. Implementation Plan

工作区已有实现。下面的顺序用于核对和补洞，不是再开一轮功能编号。

### 10.1 Phases

1. `f110`、`f111` 和 184 错误码。
2. 提交、决策、撤回、删除取消。
3. G8 投递和发分行回写。
4. 客户端按钮和待办。
5. 门户 G8 展示默认值。
6. 补 AC-11 的未解析用例，并按 RFC 核对东八区日切。

### 10.2 Issue Mapping

| 块 | SPEC | 依赖 |
|---|---|---|
| 表和错误码 | 3、6 | 无 |
| 提交和读正文 | 4.1、5.1 | 表 |
| 决策和版本 | 4.2、5.1 | 提交 |
| 发分 | 5.4、6.2 | 决策事务先提交 |
| 客户端 | 2.4、4.4 | 接口 |
| 门户展示 | 2.1 | G8 种子 |

### 10.3 Incremental Delivery

没有单独的纠错开关。G8 停用或积分总开关关闭时，处理成功但不入账。客户端必须和会把 `approve` 视同 `adopt` 的服务一起看 4.4 的兼容说明。

## 11. Open Questions & Risks

### 11.1 Unresolved Questions

- 生产库的 `knowledge_file_correction_award` 有没有需要保留的行。有则先导出，再执行 `f111`。
- 非东八区服务器上的采纳日切。验证方式在 RFC 第 11 节。

### 11.2 Technical Risks

| Risk | Impact | Mitigation |
|---|---|---|
| `f111` 删表 | 旧发分行不可恢复 | 执行前数行。降级脚本不能当备份 |
| 积分投递失败 | 已采纳但 `reserved` | 同一幂等键再投。不把纠错打回 pending |
| 只升级服务 | 旧「通过」变成采纳 | 4.4。客户端一起发 |
| 达梦未跑 | 方言差异未知 | 上线到达梦前补跑，不把 171 结果当成达梦通过 |

### 11.3 Assumptions

- 业务失败继续用现有响应包络，不新加 HTTP 状态约定。
- 门户不新增纠错接口。
- 金额、处理人和三动作以 PRD 和 RFC 为准。本文若与它们冲突，以 PRD 的用户结果和 RFC 的失败停点为准。
