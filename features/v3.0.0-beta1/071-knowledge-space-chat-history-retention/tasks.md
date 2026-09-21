# Tasks: F071 知识空间问答与目录解耦、历史对话按空间保留

**关联规格**: [spec.md](./spec.md)
**设计入口**: [design.md](./design.md)
**版本**: v3.0.0-beta1 / F071

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 2026-09-18 用户确认最终一致性、`clear_space` 与完整删除空间边界 |
| design.md | ✅ 已评审 | 2026-09-18 用户确认 best-effort 定向异步回收方案 |
| tasks.md | ✅ 已拆解 | 2026-09-18 按依赖 Wave 与 AC 覆盖自检 |
| 实现 | 🟡 开发完成，待环境门禁 | 12 / 15 完成；T013～T015 需 MySQL/DM8、运行中 worker、浏览器和脱敏快照 |

---

## 开发模式

- 后端按 Test-First 实施：先用 schema、Repository、Service、Worker、资源触发和迁移脚本测试锁定行为，再提交对应实现。
- 会话入口真相只落在 `message_session.entry_flow_id`；`flow_id`、消息和引用保持原内容链。F071 数据库逻辑只进入新增 `KnowledgeChatSessionRepository`，不得为此扩展 legacy `MessageSessionDao`。
- 在线回收采用资源提交后的 best-effort 定向 Celery 任务：默认 `countdown=5`、每批最多 500 个 flow、`acks_late`、有界重试；不增加 outbox、分布式锁、创建后复查或全量巡检。
- 删除、`clear_space` 与跨空间移动共享同一套 flow 冻结和派发合同；完整删除知识空间不新派发、不清理旧会话或入口元数据。
- 存量恢复由独立 DB-only 脚本完成，Alembic 只做 DDL；脚本默认 dry-run，apply 必须带输入摘要，并支持 checkpoint 分批提交。
- 前端 URL、`FolderSession` 与状态管理不变，不新增轮询或视觉改动；通过 API 契约测试和 E2E 验证既有页面可消费回收结果。
- 本地缺少 worktree 配置时，从 `src/backend/` 运行命令前使用
  `export config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml`；MySQL、DM8、Celery 和浏览器场景在可用集成环境验证。

---

## Tasks

### Wave 1：数据结构与 Repository 基础

- [x] **T001**: `entry_flow_id` schema 合同测试
  **文件**: `src/backend/test/knowledge/test_knowledge_chat_entry_schema.py`
  **逻辑**: 先固定 `MessageSession.entry_flow_id` 为 nullable `VARCHAR(255)`、索引名为
  `idx_message_session_entry_flow_id`；验证既有 `flow_id/create_time/update_time` 定义不变，且
  `MessageSessionDao` 不新增 F071 查询或批量回收入口。对新增 Alembic revision 做 upgrade/downgrade
  结构检查，保证 revision 只含列与索引 DDL、可幂等处理模型先建列场景，且迁移图仍为单 head。
  **覆盖 AC**: AC-11, AC-24
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_chat_entry_schema.py test/database/test_alembic_single_head.py`
  **依赖**: 无

- [x] **T002**: ORM 字段与双数据库 Alembic DDL
  **文件**: `src/backend/bisheng/database/models/session.py`,
  `src/backend/bisheng/core/database/alembic/versions/<f068_revision>.py`
  **逻辑**: 在 `message_session` 增加 nullable `entry_flow_id` 和单列索引；revision 的
  `down_revision` 取实施时唯一 head，使用共享 `column_exists/index_exists` 类 helper 防止
  `create_all()` 与升级路径冲突，upgrade/downgrade 对称且不做任何数据回填。复核 MySQL/DM8
  标识符、VARCHAR 与索引兼容性；不改变通用会话 DAO 或其它会话类型。
  **测试**: T001 全部通过；`uv run alembic heads` 只输出一个 head。
  **覆盖 AC**: AC-11, AC-24
  **设计依据**: design §3 决策 1、§4.2、§8.1
  **依赖**: T001

- [x] **T003**: effective-entry Repository 测试
  **文件**: `src/backend/test/knowledge/test_knowledge_chat_session_repository.py`
  **逻辑**: 覆盖 `entry_flow_id=target OR (entry_flow_id IS NULL AND flow_id=target)` 的互斥查询；
  验证原生 root 与 recovered root 同列且不重复、按 `create_time DESC`、tenant/owner/知识空间
  flow type/`is_delete=false` 过滤；按 `chat_id + requested_entry` 查询必须拒绝旧入口、其他空间、
  其他用户、已删除和非知识空间会话。批量回收覆盖精确 flow 集、所有合法会话 owner、仅
  `entry_flow_id IS NULL` 行，重复执行零更新；空集和超过 500 flow 的调用不产生无界 SQL。
  **覆盖 AC**: AC-10, AC-14, AC-15, AC-16, AC-18, AC-24
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_chat_session_repository.py`
  **依赖**: T002

- [x] **T004**: `KnowledgeChatSessionRepository` 合同与实现
  **文件**: `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_chat_session_repository.py`,
  `src/backend/bisheng/knowledge/domain/repositories/implementations/knowledge_chat_session_repository_impl.py`,
  两级 `__init__.py`
  **逻辑**: 提供按 effective entry 列表、按 chat+entry 取活动会话、单文件有效会话查找、按精确
  flow chunk 幂等回收到 source root 的接口；列表查询保留租户自动过滤，系统 fan-out UPDATE
  仅在实现内部受控使用 `bypass_tenant_filter()`，并显式限定知识空间 flow type、活动状态、
  `entry_flow_id IS NULL` 与传入 flow 集。Repository 不解析 HTTP、不校验资源权限、不扫描全表。
  **测试**: T003 全部通过。
  **覆盖 AC**: AC-10, AC-14, AC-15, AC-16, AC-18, AC-24
  **设计依据**: design §3 决策 2、§4.3、§4.6、坑 3/7/10
  **依赖**: T002, T003

### Wave 2：在线列表、历史与继续问答语义

- [x] **T005**: knowledge chat effective-entry 行为测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_chat_entries.py`,
  `src/backend/test/knowledge/test_knowledge_space_chat_service_retrieve.py`,
  `src/backend/test/knowledge/test_knowledge_space_chat_permissions.py`
  **逻辑**: 覆盖 root 列表合并与排序、folder/file 正常入口、recovered chat 只从原空间 root 打开、
  历史始终以数据库中真实 `session.flow_id` 读取、继续问答使用原空间 whole-space retriever 且新消息
  仍写原 flow。负向用例在消息读取/写入和 retriever 构造前拒绝：普通旧目录 chat 冒充 root、
  recovered chat 从旧入口访问、其他空间/用户/flow type/已删除 chat。验证跨空间移出再移回或同 ID
  资源重现时，单文件查找不复用 recovered session；标题、消息、引用、反馈、create_time 与消息时间
  不变，知识空间列表不因 `update_time` 变化改序。
  **覆盖 AC**: AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-17, AC-18, AC-22, AC-24
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_space_chat_entries.py test/knowledge/test_knowledge_space_chat_service_retrieve.py test/knowledge/test_knowledge_space_chat_permissions.py`
  **依赖**: T004

- [x] **T006**: chat service 与响应契约接入 effective entry
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`,
  `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`,
  `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`,
  `src/backend/bisheng/chat_session/domain/chat.py`（仅在需要接收已验证 session 时修改）
  **逻辑**: Service 先做原空间/具体资源权限校验，再通过 Repository 验证 requested entry 与 chat；
  把真实 `session.flow_id` 传给历史与消息链。recovered root 的检索范围切为原空间全量可见文件；
  单文件查找/复用按 effective entry。若 endpoint 当前直接序列化 ORM，改为显式既有字段 schema，
  确保 `entry_flow_id` 不出 API。保持会话重命名/删除通用接口、URL、错误码和非知识空间路径不变，
  不全局放宽 `ChatSessionService` 的 flow 一致性校验。
  **测试**: T005 全部通过；现有 knowledge chat citation、visibility 和 service 测试保持通过。
  **覆盖 AC**: AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-17, AC-18, AC-22, AC-24
  **设计依据**: design §3 决策 2/4/6、§4.3、坑 2/5/6
  **依赖**: T004, T005

### Wave 3：定向异步回收与资源触发点

- [x] **T007**: retention service 与 Celery worker 测试
  **文件**: `src/backend/test/knowledge/test_knowledge_chat_history_retention.py`,
  `src/backend/test/knowledge/test_knowledge_chat_history_retention_worker.py`,
  `src/backend/test/knowledge/test_celery_wiring.py`
  **逻辑**: 验证 service 只接受同一 source space 的合法 folder/file flow chunk，source root 固定为
  `space_{source_space_id}_folder_0`，空集 no-op，越界/错误 grammar 失败关闭；worker task 名固定为
  `bisheng.worker.knowledge.knowledge_chat_history_retention.rehome_knowledge_chat_sessions`，由
  `worker/__init__.py` 显式注册并命中 `bisheng.worker.knowledge.* -> knowledge_celery` 路由。覆盖
  `acks_late`、有界 retry、幂等重放，以及 dispatch/rehome/failure 日志字段和敏感内容不落日志。
  **覆盖 AC**: AC-04, AC-04A, AC-15, AC-19, AC-20
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_chat_history_retention.py test/knowledge/test_knowledge_chat_history_retention_worker.py test/knowledge/test_celery_wiring.py`
  **依赖**: T004

- [x] **T008**: retention service、worker 与任务注册实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_history_retention_service.py`,
  `src/backend/bisheng/worker/knowledge/knowledge_chat_history_retention.py`,
  `src/backend/bisheng/worker/__init__.py`
  **逻辑**: service 校验服务端生成的 source space/root/flow chunk 后调用 Repository；worker 通过共享
  worker asyncio bridge 执行，使用 `acks_late` 与有限次数 retry，输出 design §7.3 定义的结构化日志。
  提供统一 best-effort 派发 helper：去重后每 500 flow 分片、默认 `countdown=5`；捕获可预期发布异常并
  记录精确 chunk，不向资源操作抛出，不增加新 queue、Beat、broker 配置或周期巡检。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-04, AC-04A, AC-15, AC-19, AC-20
  **设计依据**: design §3 决策 3/4、§4.6、§7.3
  **依赖**: T004, T007

- [x] **T009**: 删除、清空与移动触发合同测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_chat_rehome_dispatch.py`,
  `src/backend/test/knowledge/test_knowledge_space_move.py`,
  `src/backend/test/knowledge/test_v2_filelib_unified.py`
  **逻辑**: 用调用顺序与冻结集合断言覆盖：单文件、文件夹多层子树、版本链删除；batch 混合项、重复项
  与父子同时选择先规范化；每个 `KnowledgeFileDao.adelete_batch(...)` commit 返回后立即派发且不等待
  整批结束。`clear_space` 使用删除前 `child_resources`，仅在 `only_clear=True` 提交后、空索引重建前
  派发，空空间 no-op；完整 `delete_space` 不派发、不清 session。跨空间 move 只纳入 valid item 的
  直接 move rows，在 metadata commit 后、FGA/tag/vector 等副作用前派发；同空间、invalid item 与额外
  version sibling 不派发。覆盖超过 500 flow 分片、发布失败不改变资源结果、后续副作用失败不撤销已派发
  单元、页面和直接 service 调用一致。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-04A, AC-05, AC-06, AC-07, AC-08, AC-09, AC-15, AC-19, AC-20, AC-22, AC-23
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_space_chat_rehome_dispatch.py test/knowledge/test_knowledge_space_move.py test/knowledge/test_v2_filelib_unified.py`
  **依赖**: T008

- [x] **T010**: 资源影响集合冻结与 commit 后 best-effort 派发
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**: batch 在任何删除前对 file/folder 去重，并移除已被选中祖先覆盖的顶层后代；删除在资源行消失
  前冻结实际硬删除 folder/file（含删除路径扩展出的版本链）flow，并在每个 hard-delete commit 后派发。
  `clear_space` 复用 `_list_space_child_resources` 的提交前结果，在 `async_delete_knowledge(...,
  only_clear=True)` 返回后派发，完整删空间不走此分支。跨空间 move 从 valid 直接 move rows 冻结 flow，
  在 `session.commit()` 后派发；不包含只由 `_collect_version_chain_file_ids` 补出的 sibling。所有派发均
  best-effort，不改变既有权限、channel binding、空间时间、tag、vector、MinIO 与数据库清理的相对顺序，
  不延长资源事务或等待 worker。
  **测试**: T009 全部通过；已有 delete/move/clear 回归测试保持通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-04A, AC-05, AC-06, AC-07, AC-08, AC-09, AC-15, AC-19, AC-20, AC-22, AC-23
  **设计依据**: design §3 决策 3/4、§4.3、坑 9/11/12
  **依赖**: T008, T009

### Wave 4：存量恢复脚本

- [x] **T011**: F071 存量迁移脚本测试
  **文件**: `src/backend/test/knowledge/test_migrate_f068_knowledge_chat_entries.py`
  **逻辑**: fixture 覆盖原生 root、资源仍在原空间、missing、moved、deleted space、软删会话、空消息会话、
  已有 entry、非知识空间 flow、未知 grammar 与跨 tenant 事实冲突。验证 manifest 覆盖指定 tenant 的全部
  知识空间 session，按 `(tenant_id, chat_id)` 稳定排序并排除 `entry_flow_id/update_time`；dry-run 只读、
  数据库身份不含密码、chat_id 样例掩码。apply 无 expected SHA、SHA 变化或 blocker 时拒写；分批提交后
  checkpoint 能以同一 manifest hash 续跑，且只更新活动、`entry_flow_id IS NULL` 的 recoverable orphan。
  终态必须 `recoverable_orphan_remaining=0`，非法 entry/blocker 为零；`deleted_space_skipped` 独立非阻断，
  第二次 apply 零更新且消息/引用/create_time 不变。
  **覆盖 AC**: AC-11, AC-14, AC-15, AC-16, AC-18, AC-21, AC-22, AC-24
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_migrate_f068_knowledge_chat_entries.py`
  **依赖**: T002, T004

- [x] **T012**: DB-only 存量迁移脚本与运维说明
  **文件**: `src/backend/scripts/migrate_f068_knowledge_chat_entries.py`,
  `src/backend/scripts/README.md`
  **逻辑**: 实现 folder/file/root flow grammar、资源事实分类、稳定 manifest SHA、默认 dry-run、
  `--apply --expected-input-sha256` 门禁、`--tenant-id`、`--batch-size`、checkpoint cursor 与每批独立 commit；
  跨租户读取使用受控 bypass，UPDATE 显式带 session tenant，只访问数据库且不初始化 OpenFGA/Redis/
  Milvus/ES。报告 matched/updated/update_time 刷新数、blocker 与 `deleted_space_skipped`，遵守脚本 docstring、
  argparse、非零退出码和 README 可发现性要求，不输出消息正文或配置密码。
  **测试**: T011 全部通过。
  **覆盖 AC**: AC-11, AC-14, AC-15, AC-16, AC-18, AC-21, AC-22, AC-24
  **设计依据**: design §3 决策 5、§4.4、§7.2、§8.1
  **依赖**: T004, T011

### Wave 5：集成、E2E 与交付门禁

- [ ] **T013**: Repository/Service/Worker 集成与双数据库验证
  **文件**: `src/backend/test/knowledge/test_knowledge_chat_history_retention_integration.py`,
  `features/v3.0.0-beta1/071-knowledge-space-chat-history-retention/verification.md`
  **逻辑**: 在可用 MySQL 与 DM8 环境执行 migration、effective-entry 查询和 set-based UPDATE；记录 OR 查询
  执行计划，只有双方言证明确有必要时才按 design §3 决策 2 改为 `UNION ALL` 或补复合索引。贯通
  delete/batch/clear/cross-space move → worker → root list/history/continue，核对只改 session entry，原 flow、
  消息、引用与 create_time 不变；任务扫描前提交的并发 session 被回收，扫描后提交的残余按已接受边界
  记录，不增加创建链路校验。完整删空间场景允许残留 entry，但所有 API 因空间不存在而拒绝。
  **覆盖 AC**: AC-01～AC-24（含 AC-04A）
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_chat_history_retention_integration.py`
  **依赖**: T006, T010, T012

- [ ] **T014**: F071 E2E 与前端零改动合同验证
  **文件**: `features/v3.0.0-beta1/071-knowledge-space-chat-history-retention/e2e-checklist.md`
  **逻辑**: 执行 `/e2e-test features/v3.0.0-beta1/071-knowledge-space-chat-history-retention`。用两个用户覆盖
  folder/file 会话的单删、父子批删、`clear_space`、跨空间 move、同空间 move、改名、任务重复、移出再移回；
  等任务完成后从源空间 root 查看/打开/切换/继续/改名/删除，确认检索为源空间全量、目标空间和其他用户
  不可见。验证任务完成前短暂不可见可接受、完整删除空间不可访问、页面与直接 API 一致；确认
  `chatApi.ts` URL、`FolderSession` 字段及 `useFolderChat/useFileChat` 无需新增入口状态或轮询。
  **覆盖 AC**: AC-01～AC-24（含 AC-04A）
  **依赖**: T013

- [ ] **T015**: 全量质量门禁、迁移演练与交付复核
  **文件**: 本 Feature 全部改动、`features/v3.0.0-beta1/071-knowledge-space-chat-history-retention/verification.md`
  **逻辑**: 运行 F071 聚焦测试、knowledge/chat_session 相关回归、ruff、架构守卫与 Alembic single-head；在
  脱敏快照先 dry-run，核对 DB identity、分类、`unparseable=0`、`cross_tenant_conflict=0` 和 SHA，再以
  expected SHA 演练 apply、checkpoint 续跑、终态对账和第二次零更新。复核 Celery 注册/路由、默认延时、
  retry、日志脱敏与非知识空间回归；把 MySQL/DM8、API/E2E、未执行项和环境限制写入 verification，最后执行
  `/code-review --base <merge-base>`，不得把旧镜像回滚或清空 entry 当成功回滚方案。
  **覆盖 AC**: AC-01～AC-24（含 AC-04A）
  **验证**:
  - `cd src/backend && uv run pytest test/knowledge/ -k "chat or move or filelib"`
  - `cd src/backend && uv run pytest test/chat_session/ test/database/test_alembic_single_head.py`
  - `cd src/backend && uv run ruff format --check bisheng/knowledge bisheng/worker/knowledge scripts/migrate_f068_knowledge_chat_entries.py test/knowledge`
  - `cd src/backend && uv run ruff check bisheng/knowledge bisheng/worker/knowledge scripts/migrate_f068_knowledge_chat_entries.py test/knowledge`
  - `cd /Users/zhangguoqing/works/bisheng/.worktrees/feat-923-3.0.0-beta1 && bash scripts/arch-guard.sh`
  **依赖**: T014

---

## 实际偏差记录

> 只留一行指针，论证写入 design.md。若实施发现必须推翻已确认的 entry 字段、best-effort 一致性、
> 完整删除空间边界或存量迁移合同，先暂停并重新确认，再更新 design 与本节。

- 测试基建适配：共享 SQLite `knowledge` DDL 补齐既有 F050 creation-idempotency 两列，v2 filelib
  单测改用当前 `get_open_api_operator[_async]` 接口；仅修正测试与现行模型/接口的漂移，不改变生产语义。
- T014 已生成环境门禁式 API E2E 与手工清单；当前无专用测试租户 JWT 和运行中 worker，测试收集结果为
  `4 skipped`，不标记任务完成。
