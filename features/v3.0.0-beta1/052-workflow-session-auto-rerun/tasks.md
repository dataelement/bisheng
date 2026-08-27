# Tasks: F052 工作流会话打开时自动重新运行

**关联规格**: [spec.md](./spec.md)
**设计入口**: [design.md](./design.md)
**版本**: v3.0.0-beta1 / F052

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 2026-08-27 用户确认 |
| design.md | ✅ 已评审 | 2026-08-27 用户确认；接手第一入口 |
| tasks.md | ✅ 已拆解 | 2026-08-27 按 tasks checklist 自检 |
| 实现 | ✅ 已完成 | 9 / 9 完成；专用环境的页面手动 E2E 待执行 |

---

## 开发模式

- 后端先用配置契约和 `WorkflowClient.check_status` 单元测试锁定行为，再修改配置与 WebSocket 协议。
- client 先以纯策略单元测试固定“当前激活、明确标记、只消费一次”，再接入现有 WebSocket hook。
- 独立页配置加载单独测试成功与失败关闭，防止 `/env` 时序造成漏触发或阻断页面。
- 不修改 platform 系统配置页面：它已经是实例级 YAML 编辑器，新键由模板与注释直接呈现。
- 不新增数据库迁移、Recoil atom、第三方依赖、错误码或用户文案。

---

## Tasks

### Wave 1：先锁定配置、状态协议和前端策略

- [x] **T001**: 系统统一开关配置契约测试
  **文件**: `src/backend/test/common/test_workflow_auto_rerun_config.py`
  **逻辑**: 验证 `WorkflowConf` 默认 false、显式 boolean、缺失/错误类型 fail-safe false；验证
  `initdb_config.yaml` 包含 `workflow.auto_rerun_on_open: false`；验证 `/env` 只返回归一化布尔值；验证旧
  `workflow` 段缺键时由现有 merge 补入且不覆盖已有值。
  **覆盖 AC**: AC-01, AC-02
  **验证**: `cd src/backend && uv run pytest test/common/test_workflow_auto_rerun_config.py`
  **依赖**: 无

- [x] **T002**: 打开时已结束的 WebSocket 状态标记测试
  **文件**: `src/backend/test/workflow/test_workflow_auto_rerun_status.py`
  **逻辑**: mock Redis callback、历史消息和发送函数；断言无状态以及检查前已是 SUCCESS/FAILED 时最终 close
  带 `workflow_status_checked/finished` 标记，终态待发送事件先排空；RUNNING/WAITING/INPUT、工作流下线、
  检查后才结束的 close 均不带标记；新会话 init 不产生历史结束标记。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-11
  **验证**: `cd src/backend && uv run pytest test/workflow/test_workflow_auto_rerun_status.py`
  **依赖**: 无

- [x] **T003**: client 自动重跑激活策略单元测试
  **文件**: `src/frontend/client/src/pages/appChat/workflowAutoRerun.test.ts`
  **逻辑**: 验证仅独立工作流、开关开启、非新会话、当前 chat 且明确 status-check finished 标记同时满足时
  返回 auto；普通 close、助手、非独立页、开关关闭、新会话、迟到 chat 均返回 manual/ignore；同一 activation
  只消费一次，A→B→A 后新的 A activation 可再次消费。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-13
  **验证**: `cd src/frontend && pnpm --filter bishengchat test:ci -- --runInBand workflowAutoRerun.test.ts`
  **依赖**: 无

### Wave 2：实现后端配置与明确状态协议

- [x] **T004**: 系统配置与 `/env` 下发实现
  **文件**: `src/backend/bisheng/core/config/settings.py`,
  `src/backend/bisheng/initdb_config.yaml`, `src/backend/bisheng/api/v1/endpoints.py`
  **逻辑**: 在 `WorkflowConf` 增加严格 fail-safe 的 `auto_rerun_on_open: bool = false`；模板 `workflow` 段
  增加带注释默认项；`get_env` 下发 `workflow.auto_rerun_on_open`，不返回其他工作流运行参数。
  **测试**: T001 全部通过；现有 config backfill 测试保持通过。
  **覆盖 AC**: AC-01, AC-02
  **依赖**: T001

- [x] **T005**: 状态检查 finished 标记实现
  **文件**: `src/backend/bisheng/common/chat/clients/workflow_client.py`
  **逻辑**: `check_status` 在有历史且检查瞬间无 Redis 状态时直接发带标记 close；检查瞬间已经是
  SUCCESS/FAILED 时先复用既有响应排空/清理，再让最终 close 带同一标记；非终态继续恢复且后续 close 不带
  标记。保持下线、新会话和其他客户端兼容。
  **测试**: T002 全部通过。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-11, AC-12
  **依赖**: T002

### Wave 3：接入 client 独立会话并隔离竞态

- [x] **T006**: 自动重跑纯策略与 WebSocket 接线
  **文件**: `src/frontend/client/src/pages/appChat/workflowAutoRerun.ts`,
  `src/frontend/client/src/pages/appChat/useWebsocket.ts`, `src/frontend/client/src/pages/appChat/useChatHelpers.ts`
  **逻辑**: 实现 activation guard 与严格标记判定；抽取手动/自动共用的 workflow `init_data` 构造发送；
  自动命中时直接启动并设置运行中 UI，普通运行期 close 只展示手动重跑；把模块级单槽 callback 改成按 chat id
  隔离，关闭会话时清理；迟到事件不得自动执行。
  **测试**: T003 全部通过；既有手动重跑行为保持。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13
  **依赖**: T003, T005

- [x] **T007**: 独立页配置加载行为测试
  **文件**: `src/frontend/client/src/pages/standaloneChat/StandaloneChatPage.test.tsx`
  **逻辑**: mock `/env`、sidebar 和 AppChat；验证配置成功时 provider 获得 boolean，配置完成前不挂载 AppChat；
  请求失败、字段缺失/错误时按 false 继续渲染；guest/auth 与 workflow/assistant 范围正确。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-13
  **验证**: `cd src/frontend && pnpm --filter bishengchat test:ci -- --runInBand StandaloneChatPage.test.tsx`
  **依赖**: T003

- [x] **T008**: 独立页读取并传递统一开关
  **文件**: `src/frontend/client/src/pages/standaloneChat/StandaloneChatPage.tsx`,
  `src/frontend/client/src/pages/standaloneChat/StandaloneChatContext.tsx`,
  `src/frontend/client/src/@types/chat.ts`
  **逻辑**: 两类 standalone 页面通过既有 API wrapper 加载 `/env`；读取完成或失败降级后才挂载活动会话；
  将归一化后的策略放入已有页面上下文，非 standalone 消费方保持 false；不新增 Recoil atom。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-13
  **依赖**: T006, T007

### Wave 4：综合验证与交付

- [x] **T009**: F052 E2E、质量门禁与代码审查
  **文件**: `features/v3.0.0-beta1/052-workflow-session-auto-rerun/e2e-checklist.md`
  **逻辑**: 按 e2e-test 工作流覆盖开关关闭/开启、guest/auth 首次进入与切换、运行中/等待输入恢复、
  正常完成/失败/人工停止/断网后不重试、快速切换与手动重跑；执行后端 focused tests、client focused tests、
  `pnpm lint`、`pnpm typecheck`、arch-guard 和 diff review，区分功能失败与环境基线失败。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13
  **依赖**: T004, T005, T006, T008

---

## 实际偏差记录

- 分支使用 `feat/3.0.0-beta1-052-workflow-session-auto-rerun`，因为 Git 已存在
  `feat/3.0.0-beta1`，无法再创建同名前缀下的 `feat/3.0.0-beta1/052-*` 引用。
- `StandaloneChatPage.test.ts` 在 Node 环境直接覆盖页面使用的配置加载策略；当前本地 jsdom 的可选
  `canvas.node` 缺失，因此未增加依赖原生 canvas 的页面挂载测试。
- live E2E 为只读测试并默认跳过，需在包含 F052 构建的专用环境设置 `F052_E2E=1` 后执行；页面场景已写入
  `e2e-checklist.md`。
- `pnpm typecheck` 的 platform 阶段被两个既有测试错误阻断：
  `src/test/f048DashboardPermissions.test.tsx:91` 与 `src/test/routeFilterPurity.test.ts:16`；本次涉及的 client
  `pnpm --filter bishengchat typecheck` 已通过。
