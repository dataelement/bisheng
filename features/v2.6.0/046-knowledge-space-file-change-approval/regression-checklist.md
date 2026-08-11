# F046 回归检查清单

**Feature**: 知识空间文件与文件夹变更审核
**覆盖基线**: F025 / F027 / F029 / F030 / F034 / F044 / F045
**记录日期**: 2026-08-11
**说明**: 本文只记录实际执行结果、已知环境基线和最终交付门禁；测试文件存在、被 collect 或默认 skip 均不等于功能通过。

## 1. 结果口径

- `通过`：命令已实际执行且退出码为 0。
- `聚焦通过`：本地聚焦集合已实际执行且退出码为 0；不替代真实外部存储、DM8 或 live E2E。
- `已收集`：pytest/Jest 能发现测试；没有执行断言或 live 场景，不计为通过。
- `未执行`：缺少 live 环境、依赖或尚待最终实现收敛；不得写成 skip 后通过。
- 所有命令均以 worktree `/Users/zhangguoqing/works/bisheng.worktrees/feat-2.6.0-cofco-0811` 为基准。

## 2. 已确认的自动化结果

### 2.1 后端聚焦测试

| 测试集合 | 已确认结果 | 当前口径 | 仍需外部验证 |
|---|---:|---|---|
| owner + visibility + citation + scanner + worker 聚焦集合 | `114 passed` | 最终本地聚焦通过；覆盖 transition projection、citation、cleanup crash recovery 和 worker | 真实 ES/Milvus/OpenFGA/Redis |
| F046 完整本地后端集合 | `380 passed` | 当前 worktree 最终复跑退出码为 0；同时覆盖 upload stage/MinIO lifecycle、部门私密和频道边界 | DM8、真实中间件、live E2E，以及 §4 所列本地基线 |
| AC-04 bulk 配置 API + UoW、AC-07/40/41/42 直接回归及频道/F045 边界 | `67 passed` | 聚焦通过；覆盖已发起实例不受新策略影响、个人 owner/editor、分享关系不变、频道模块无 F046 依赖 | 真实 OpenFGA 角色变化与 Platform live 保存 |

最终集合使用后端项目配置启动，退出码为 0：

```bash
cd src/backend
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml uv run pytest \
  test/knowledge/test_file_change_* \
  test/approval/test_file_change_* \
  test/knowledge/test_knowledge_space_upload_stage.py \
  test/knowledge/test_minio_tagged_expiration.py \
  test/department/test_department_space_private_forbidden.py \
  test/channel/test_file_change_approval_boundary.py
```

关键 owner/Decision UoW/Deferred/动态审批/Worker 文件族也包含在上述 `380 passed` 集合中：

```bash
cd src/backend
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml uv run pytest \
  test/approval/test_approval_gate_uow.py \
  test/approval/test_approval_decision_uow.py \
  test/approval/test_dynamic_approver_service.py \
  test/approval/test_approval_runtime_dynamic_hooks.py \
  test/approval/test_approval_deferred_outbox.py \
  test/approval/test_approval_worker_deferred.py \
  test/approval/test_file_change_scenario_registry.py \
  test/approval/test_file_change_approver_reconcile_worker.py \
  test/approval/test_file_change_execution_worker.py \
  test/approval/test_file_change_beat_schedule.py \
  test/approval/test_file_change_compensation_scan.py \
  test/knowledge/test_file_change_execution_coordinator.py \
  test/knowledge/test_file_change_production_mutation_step_owner.py \
  test/knowledge/test_file_change_rename_move_saga.py \
  test/knowledge/test_file_change_delete_cutover.py
```

新增验收点的直接回归命令：

```bash
cd src/backend
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml uv run pytest -q \
  test/knowledge/test_file_change_policy_api.py \
  test/knowledge/test_file_change_policy_service.py \
  test/knowledge/test_file_change_request_service.py \
  test/channel/test_file_change_approval_boundary.py \
  test/approval/test_channel_subscription_approval_integration.py \
  test/channel/test_channel_authorization_service.py::test_channel_direct_operations_unchanged \
  test/approval/test_resource_user_invite_handler.py::test_dispatches_to_resource_owner_service \
  test/approval/test_approval_decision_uow.py::test_f045_self_confirmation_still_rejects_admin_and_accepts_target
```

### 2.2 Client 聚焦测试

以下纯逻辑测试均使用 Node 环境执行，避开本机缺失的可选 canvas native binary；这不替代 jsdom 组件测试。

| 测试 | 结果 | 覆盖重点 |
|---|---:|---|
| `useFileUpload.test.ts` | `12/12 passed` | opaque upload_id、逐项 direct/pending/invalid、幂等重试 |
| `useFileManager.test.ts -t "knowledge file mutation decisions"` | `9/9 passed` | 单条/批量 rename/move/delete 决策、pending 保留、single invalid |
| `FileChangeApproval.test.tsx` 的纯投影集合 | `6/6 passed` | 根/继承锁、状态与动作投影；cursor hook 的 jsdom 用例见 §4 环境基线 |
| `approvalCenterFileChangeUtils.test.ts` | `7/7 passed` | 处理后选择下一条、business projection |

```bash
cd src/frontend/client
pnpm exec jest --ci --runInBand --env=node src/pages/knowledge/hooks/useFileUpload.test.ts
pnpm exec jest --ci --runInBand --env=node src/pages/knowledge/hooks/useFileManager.test.ts \
  -t 'knowledge file mutation decisions'
pnpm exec jest --ci --runInBand --env=node \
  src/pages/knowledge/SpaceDetail/FileChangeApproval.test.tsx \
  -t 'batch-merges|uses the latest|distinguishes|selects only|describes|summarizes'
pnpm exec jest --ci --runInBand --env=node \
  src/components/approval/approvalCenterFileChangeUtils.test.ts
```

聚焦 ESLint 对 F046 Client API、上传拆分 hooks、mutation hooks、状态/详情/待审批面板及 Approval Center 相关文件退出码为 0。三种语言各新增 `34` 个 `file_change` keys，JSON 结构和 key path 已确认对齐。

### 2.3 Platform 聚焦测试

| 测试 | 结果 | 覆盖重点 |
|---|---:|---|
| `src/test/fileChangeApprovalSettings.test.tsx` | `15/15 passed` | 当前租户 API、总控/多空间一次 bulk PUT、失败保持 dirty、重试后才更新基线 |

```bash
cd src/frontend/platform
pnpm test -- src/test/fileChangeApprovalSettings.test.tsx
```

### 2.4 E2E 测试资产

| 项目 | 结果 | 结论 |
|---|---:|---|
| `test_e2e_f046_file_change_approval.py` + `test_e2e_f046_file_change_visibility.py` | `14 collected` | 仅证明测试可收集 |
| 默认未设置 `E2E_F046_ENABLED=1` | `14 skipped`（设计行为） | 未调用写 API，不是 E2E 通过 |
| live 双租户 + Celery + RAG + 解析失败注入 | 未执行 | 必须在授权测试环境按 `e2e-checklist.md` 执行 |

收集命令：

```bash
cd src/backend
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml uv run pytest --collect-only -q \
  test/e2e/test_e2e_f046_file_change_approval.py \
  test/e2e/test_e2e_f046_file_change_visibility.py
```

## 3. 静态检查

| 检查 | 已确认结果 | 注意 |
|---|---|---|
| 后端 F046 新增文件 Ruff | `72 files, All checks passed` | 触及的大型旧文件仍有历史 Ruff 债务，不把全量旧错误算作本功能通过 |
| F046 Client 精确 ESLint | 通过 | 仅检查本功能修改/新增的 API、事件、审批组件、空间页和 hooks |
| Platform 全量 lint | 通过 | workspace `pnpm lint` 先完成 Platform，随后在 Client 既有问题处失败 |
| workspace i18n + locale artifact check | 通过 | `pnpm check-i18n` 与 `pnpm --filter @bisheng/locales check` 均退出码 0 |
| `bash scripts/arch-guard.sh` | 通过 | 最终并行实现收敛后的本地结果 |
| `git diff --check` | 通过 | 最终并行实现收敛后的本地结果；只检查 whitespace，不证明功能正确 |
| F046 文档相对链接/代码锚点检查 | 通过 | `spec/design/tasks/e2e/regression` 与审批 skill 当前路径可解析 |

## 4. 明确的环境与历史基线

这些项目不得归因于本次测试通过，也不得静默忽略：

| 基线 | 当前事实 | 最终验证位置 |
|---|---|---|
| DM8 | 本地未执行 DM8 DDL、Repository 和事务回归；Alembic autogenerate 也只反射 MySQL | 中央 CI / DM8 测试环境 |
| MySQL/Redis/MinIO/OpenFGA/ES/Milvus | 本地没有完整授权的多租户中间件组合，未执行真实跨存储 transition/purge E2E | 集成 CI + live E2E |
| Redis | 本机 Redis 不可用，Lua integration 集合曾有 `27 skipped`；不能标成通过 | 有 Redis 的 CI/测试环境重跑 |
| Client canvas/jsdom | `ApprovalCenterDialog.test.tsx` 在 suite 收集前因既有可选依赖 `canvas.node` 缺失失败 | 安装匹配 native binary 的前端 CI 重跑完整组件 suite |
| Client typecheck | Platform `349` 个 strict files 全通过；Client 仍仅有两处既有错误：`AgentToolSelector.tsx:132`、`ChatFormTools.tsx:118` | 不把它们记为 F046 新增；CI 仍须按仓库规则处理 |
| Client 全量 lint | 仍有 `46` 个既有错误，集中于 `chatApi.ts`、`ThinkingContent.tsx`、`UserPopMenu.tsx`、`useChatHelpers.ts`、`useWebsocket.ts`、`FilePreview/index.tsx`，均非 F046 修改文件 | F046 精确 ESLint 已通过；全量债务需独立基线修复后再过 workspace lint |
| `test_knowledge_space_service.py` 全文件 | 既有环境/旧 mock 签名基线曾为 `56 passed, 26 failed`，包含 DM driver 与旧 mock 不匹配 | 聚焦归因后由中央回归确认 |
| 最新 F046 本地后端复跑 | `380 passed`；此前 13 个失败中的 3 个顺序依赖定位为 auto tenant filter 把 stage 左连接改成内连接，已改为显式 tenant 子查询并复跑全绿 | 真实 DM8/中间件/live E2E 仍需外部环境 |
| live E2E | 未执行，14 条仅 collect/默认 skip | `E2E_F046_ENABLED=1` 且明确授权的隔离环境 |
| orphan stage 生命周期 | 未绑定对象仅写临时 bucket 并由其生命周期删除；申请绑定后以稳定键复制到永久 bucket，Beat 只补偿复制并在确认临时对象不存在后对账元数据/配额 | 真实 MinIO 环境验证临时对象到期删除、绑定复制幂等和永久对象保留 |

## 5. Feature 回归矩阵

| Feature / 不变量 | 自动化证据 | 仍需 live/CI 确认 |
|---|---|---|
| F025 普通 OR/AND、多节点、withdraw、exception | F046 Approval file-change 聚焦集合通过；通用 F025 回归不在通配集合内 | 普通场景通知与异常管理 UI、全量 F025 CI |
| F045 邀请本人确认 | F046 变更对 F025 接口的聚焦回归通过；F045 专属全量不在通配集合内 | 邀请专属通知、不可代办、授权完整生效 |
| AC-04 原子配置保存 | bulk API/UoW rollback、跨租户空间拒绝和 Platform 单请求组件测试通过 | MySQL/DM8 事务与 Platform live 保存 |
| AC-07 策略仅影响后续申请 | pending 实例 + 策略切换 + 后续 direct 的直接回归通过 | live 审批人处理旧申请 |
| F027 cursor children/search | visibility guard 聚焦测试通过 | 长列表 cursor 无重复/丢行、无 total 回退 |
| F029 RAG/citation | guard/citation 聚焦测试通过 | 解析中、delete cutover、transition projection 的真实 ES/Milvus 查询 |
| F030 OpenAPI | v2 guard 聚焦测试通过 | 代用户、跨租户、列表/详情/检索 live 验证 |
| F034 move | rename/move saga、owner 与 projection 测试通过 | 同/跨空间真实标签、FGA parent、索引/对象迁移 |
| F044 权限配置 | owner/manager trigger 与 strict resolver 聚焦测试通过 | 权限变化后的 live 动态候选发现、former approver 不可见 |
| AC-40 个人空间角色语义 | strict resolver 下 owner direct、editor pending 的直接回归通过 | 真实个人空间 OpenFGA userset |
| AC-41 集团/部门分享语义 | bulk 保存前后 Knowledge auth、部门绑定、SPACE member/relation 不变的回归通过 | Platform 私密选项与真实分享链路 |
| AC-42 频道/F045 隔离 | channel domain import/route 边界、频道直通/订阅审批、F045 本人确认聚焦回归通过 | 频道与邀请 live 主流程 |
| F046 免审直通 | request service / mutation API 聚焦测试通过 | 总开关关闭、单空间无需审核、private、owner/manager 四类 live 直通 |
| 部门空间不可 private | department service/API 聚焦测试通过 | Platform 隐藏选项 + 服务端 18075 live 验证 |

## 6. 最终交付门禁

- [x] 并行实现最终收敛后重跑 F046 本地后端集合：`380 passed`，退出码为 0。
- [x] AC-04/07/40/41/42 直接回归 `67 passed`，Platform 组件 `15/15 passed`，相关 Ruff/ESLint 通过。
- [x] 重跑 Client 聚焦 Jest、F046 精确 ESLint 和 workspace i18n：上传 `12/12`、mutation `9/9`、投影 `6/6`、Approval Center utils `7/7`，`check-i18n` 通过。
- [ ] Client 完整 jsdom suite 仍被本机缺失 `canvas.node` 阻断；全量 Client lint/typecheck 仍有 §4 记录的既有非 F046 基线。
- [ ] 在 MySQL 与 DM8 验证 migration upgrade/downgrade 前置检查、唯一约束、JsonType、NULL/cursor/LIKE escape。
- [ ] 在 Redis/MinIO/OpenFGA/ES/Milvus + default celery + knowledge_celery + Beat 完整环境执行 live E2E；保留 run-prefix 清理记录。
- [ ] 按 [e2e-checklist.md](./e2e-checklist.md) 执行 Platform、Client、审批中心和动态审批人手工验证并记录截图点。
- [x] 并行改动结束后再次执行相关文件 Ruff、`bash scripts/arch-guard.sh` 与 `git diff --check`。
- [x] 确认 `.claude/skills/approval-module/SKILL.md` 的 F046 owner、projection、Beat cleanup、API 和通知锚点与代码一致；MinIO 管物理过期删除，应用只做 tag 保留补偿与元数据对账。

**当前整体状态**: 后端 F046 本地集合 `380 passed`；AC-04/07/40/41/42 直接回归 `67 passed`；Platform
`15/15 passed` 且 strict typecheck 全绿；Client F046 聚焦逻辑与精确 ESLint、workspace i18n 全绿。live E2E、DM8、
真实 MinIO/OpenFGA/ES/Milvus/Redis 集成和 Client jsdom native 环境仍未执行，不能宣称跨存储生产级全量回归通过。
