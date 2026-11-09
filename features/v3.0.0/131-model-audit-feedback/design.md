# Design: 桌面消息审计评价

关联 [spec.md](./spec.md) · [tasks.md](./tasks.md)。v3.0.0 work-130，2026-11-09 按 PR #2646 `c6f182a5d7` 与本轮修复补记实现。遵循 `docs/constitution.md`，领域归属继承 F062 DSH 与现有模型审计。

## 1. 目标与非目标

反馈附着当前用户的审计会话，目录显示赞踩数量，详情独立展示消息评价。保持模型调用、审计原文和消息历史边界；不增加评价到模型的输入。

## 2. 关键约束

写入经过既有设备身份认证、principal_scope 和 profile_scope。正文最多 16 KiB，备注最多 8192 UTF-8 字节；序号为 JavaScript 安全非负整数。模型关闭审计且没有可展示安全记录时拒绝/禁用反馈。审计列表仍沿用现有管理权限与查询范围。

## 3. 方案与决策

评价使用独立 SQL 表，键为由 tenant/user/conversation 派生的 conversation_key 加 message_id。备选将消息编号塞入模型请求或网页聊天历史，会错误制造请求对应关系，因此不采用。

撤销采用独立 `DshModelAuditFeedbackRetraction` 表保存身份键、event_seq 和 received_at，原评价行连同备注删除。备选直接删行会丢失最大已接受序号，迟到的旧 put 重新建行；在原 rating 枚举中加入“已删除”又要求已有表约束演进。独立水位表无需修改已有评价表结构，只由模型发现机制创建缺失表，可兼容先前测试过该 PR 的环境。水位只在接受更高序号 put 后移除；该事务中新反馈行接替水位职责。若未来改变事件序号作用域或审计保留周期，需要同时评估两表状态的清理与晚到请求边界。

调用 `lock_retention()` 先锁住租户的审计设置行；不存在则创建并 flush，冲突由 Service 的 IntegrityError 重试重新开始事务，不能把“没有查到行”当成可移植互斥锁。之后读取活动反馈及撤销水位并锁行，比较序号，在同一事务内替换状态。

## 4. 系统现状与数据流

`POST /api/v1/dsh/audit/message-feedback` → desktop_principal → schema 验证 → DshModelAuditFeedbackService → DshModelAuditFeedbackRepository → 当前租户/用户的审计会话检查 → 事件 CAS → SQL 提交。`/dsh/settings` 的能力声明增加 audit_message_feedback.version=1。

请求字段为 conversation_id、message_id、event_seq、op=put/delete；put 需要 rating=positive/negative，可含 category/note；delete 不允许评价内容。返回 status 为 UPDATED/UNCHANGED/STALE/CONFLICT/NOT_READY/DISABLED，已接受/冲突序号通过 event_seq 返回。

活动行在 `dsh_model_audit_message_feedback`，撤销行在 `dsh_model_audit_feedback_retraction`，两者在一个消息上互斥。相同序号在活动行上仅相同 put 为 UNCHANGED，在撤销行上仅 delete 为 UNCHANGED，其余冲突；低序号统一 STALE。尚不存在活动评价的 delete 仍保存水位，但沿用 UNCHANGED 响应。查询只读活动表，因此水位不计数、不返回详情。

前端 `controllers/API/dshModelAudit.ts` 解析独立反馈数组；nonnegative 使用 `value is number` 类型谓词，运行时校验与静态缩窄一致。ModelAuditGroup/Tree 显示数量与详情。

## 5. 已知坑

| 事实 | 忽略的后果 | 处理 |
| --- | --- | --- |
| 删除评价不能删除其事件历史水位 | seq=14 撤销后 seq=12 的重试恢复评价 | 独立 Retraction 表与同事务替换 |
| 没有设置行时 FOR UPDATE 不提供跨 DB 的行互斥 | 并发首写产生跨表矛盾状态 | lock_retention 的唯一租户行插入和事务重试 |
| boolean 校验函数不一定缩窄对象字段 | event_seq 赋值触发 TS2322，CI 无法通过 | 显式 number 类型谓词 |

## 6. 对外契约与依赖

依赖既有 DSH 身份、审计模式、审计请求存储、管理端查询与租户过滤。新增模块已在 tenant_filter 的模型模块清单中；新水位模型同属该模块。独立新表沿用模型发现/create_all(checkfirst=True)；不改变已有字段，不需要 Alembic ALTER。接口不得被模型调用路径调用；故障不应改变 token 计费和模型调用次数。

## 7. 测试与可观测

test/dsh/test_model_audit_feedback.py 通过真实路由/Service/Repository 和 SQLite 验证输入、错误脱敏、CAS、撤销先到、旧请求重放、相同撤销重试、新评价替代水位，并重新查询计数/详情。身份和模型提供者使用测试夹具；MySQL/DM8 实际并发锁由中央环境验收，不声称 SQLite 可证明两者锁语义。前端解析器和审计组件测试配合完整 lint/typecheck 验证。

## 8. 后续边界与修订

真实 Desktop 与管理端完整验收由部署后的匹配版本环境执行；本设计不将合成身份测试冒充现场验收。2026-11-09 补记现有契约，并记录序号水位修复和独立新表升级策略。
