# 116 两条任务失败根因与实际进度

只读复查：2026-11-17。核对 SQL、运行代码、持久 worker 日志和限定索引的 HEAD/计数查询；事务 READ ONLY 后回滚。本轮没有重试、回退、放弃、删除或改任务/权限数据。时间以 UTC+8 日志为主，数据库任务时间为 UTC。

## 1. 移动：3547 → 4394

任务 688eded7-a37a-46af-9847-901fcf4f46d9；计划 49231922-e7d5-4be3-b7f1-98105053d9e3。

- 15:57:35 接收，15:58:31 开始，15:58:36 失败；两个 item attempt=1、step=pending，checkpoint 含已完成 logical_move，job 含有效 move_logical_marker。
- 文件 98364「20260413-165751.mp4」和 98365「20260413-174108.mp4」当前 SQL knowledge_id 均为 4394，status=3，remark 记录 10953。说明归属已经移动；item 的成功数 0 仅表示索引处理未完成。
- 日志 `bisheng.2026-11-17_15-33-24_988920.log:7574` 及 `:7762`，两个 item 均先执行目标 ES 索引 HEAD，返回 404；底层异常 `ValueError: move physical ES index is missing`，随后包装成 10953 `move_index_update_failed`。不是已证实的视频解析错误。
- 4394 本身存在 2026-11-13 创建的失败 space_copy 任务 f79e78e0-1a9f-474f-bd26-0608e5105a77（11 项、25008）；当前空间 state=0。接受本次移动时，目标并未完成索引初始化。
- **当前事实已变化**：复查时源、目标 ES 均 HEAD 200；目标创建时间为 2026-11-17 08:24:33.040 UTC（16:24:33），晚于移动失败。按这两个确切文件 ID 查询 ES，源 2 条分段、目标 0 条。不能继续将“目标索引不存在”描述为当前现状，也不能据此认为移动已经恢复。

根因：逻辑归属切换先发生，后续 worker 才遇到未就绪目标的物理 ES 缺失。产品/代码需要在逻辑切换前验证目标可执行或完成 owner 初始化，并向用户展示阶段事实。索引最初为何没有初始化，与目标原失败复制相关；本轮没有尝试恢复旧复制。

## 2. 复制：3547 → 4410

任务 66d6a76e-56ff-4937-adb2-fa80b9edfb3f；计划 6fa9278b-0bdf-4a67-8ea4-53c4da028034。

- 16:53:51 接收，16:54:35 开始，16:55:40 失败；30 个文件 item 全失败、attempt=0、started_at=NULL、step=pending，说明内容执行尚未开始；目标 SQL 已有 30 个 status=5 文件记录及 1 个文件夹。
- `move_logical_marker` 为 **JSON null**，不是有效 marker；先前只用 SQL IS NOT NULL 检查该列会把 JSON null 误当作存在，不能据此推断逻辑完成。
- 日志 `bisheng.2026-11-17_16-28-45_581718.log:207990` 及 `:221517`：owner.astart → aensure_logical → permission KnowledgeCopyProjectionApplication.aexecute_or_resume:152 → `Copy projection no longer matches its original complete operation`（25008）。两次尝试在同一校验点阻断。
- Root 目标权限 operation 3821，scope=knowledge_space:4410，operation_type=RESOURCE_COPY，status=FINALIZED，无 error_code。源、目标对应授权均 ACTIVE/CURRENT，主体和模型一致，但来源编码不同：

| 授权 | 源 3547 的 source_ref | 副本 4410 的 source_ref |
| --- | --- | --- |
| DIRECT manager | user:686\|manager\|knowledge_space:3547\| | user:686 |
| DEPARTMENT viewer | department:142#member\|viewer\|knowledge_space:3547\| | 142#member |
| CREATOR owner | creator:knowledge_space:3547 | knowledge_space:4410 |

两个普通授权的 source_fingerprint 也因规范化变化而不同。运行代码逐项 signature 比较包含 source_ref/source_fingerprint，直接将源 wanted 与目标 found 比较，因上述格式差异触发 wanted != found；该条件发生在开始文件内容 item 之前。目标创建者保护来源符合目标格式，不能把整个错误笼统归因为“没有权限”。

根因：合法来源复制/规范化后的表示变化，与后置校验所要求的原始字段逐字相等不一致。修复应在 permission owner 中用已有复制规则构造目标预期授权，仍严格验证冻结操作、实际授权集合和保护所有者，不能直接删除安全校验。

## 3. 为什么阻止删除及用户应看到的说明

SourceMoveInputRepository 看到源 3547 的两个已消费计划仍未完整成功，因此拒绝删除。该保护有实际意义：移动的分段仍在源索引，复制的目标内容尚未完成，不能先移除其恢复输入。

建议任务进度显示：

| 任务 | 文件记录/归属 | 内容/索引处理 | 阻断阶段 |
| --- | --- | --- | --- |
| 移动到 4394 | 已变更归属 2/2 | 索引迁移 0/2；源清理 0/2 | 执行时目标索引不存在 |
| 复制到 4410 | 已创建文件记录 30/30（另有文件夹 1 个） | 内容复制 0/30 | 权限复制结果校验失败 |

已实施的提示修复使用现有 10999 + reason=source_space_move_input_required：明确说明未完成/失败的复制或移动仍需要源文件，需处理后再检查删除。逐条任务摘要、阶段进度及处理入口属于待确认的新任务契约，不能在尚未实现时声称已经提供。

## 4. 放弃与整体回退的现场边界

- 放弃后续处理并不自动恢复位置：移动需验证目标原始文件可读，并将未完成索引明确标为待处理；复制只保留完整可用副本，不能将 30 个占位记录当作成功成果。
- 整体回退：移动可候选恢复这两个文件的原归属及权限，源索引仍有数据是有利条件；复制可候选移除本任务占位和复制空间。两者都必须先比较原 snapshot 与当前文件/权限/引用，拒绝覆盖后续修改；本轮没有证明全部回退条件已满足。
- 只有经 owner 完成善后、核对对象/索引/权限并持久记录源输入不再被依赖，才能释放对应保护。删除记录、改成成功或手动置空 marker 都不属于放弃/回退方案。
