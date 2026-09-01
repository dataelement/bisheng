# Tasks: F051 知识库列表动作权限懒加载

**关联规格**: [spec.md](./spec.md)
**设计入口**: [design.md](./design.md)
**版本**: v3.0.0-beta1 / F051

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 2026-08-25 用户确认 |
| design.md | ✅ 已评审 | 2026-08-25 用户确认；接手第一入口 |
| tasks.md | ✅ 已拆解 | 2026-08-25 `/sdd-review tasks`: LGTM |
| 实现 | ✅ 已完成 | 8 / 8 完成；live E2E 待部署专用环境按清单执行 |

---

## 开发模式

- 后端先以现有 visible-first 单元测试锁定调用次数和返回 actions，再修改 Service。
- 前端先测试 imperative lazy hook 的显式触发、缓存和隔离，再接入文档/QA 两个列表。
- Wave 1 的后端测试与前端 hook 测试无依赖；Wave 2 分别实现；Wave 3 接入页面并补组件测试；Wave 4
  执行 E2E 清单和质量门禁。
- 不修改或暂存当前工作区中与 F051 无关的脚本、权限组件及其测试。

---

## Tasks

### Wave 1：先锁定行为（可并行）

- [x] **T001**: 知识库列表最小 actions 后端回归测试
  **文件**: `src/backend/test/knowledge/test_knowledge_list_visible_first.py`
  **逻辑**: 将 visible、use、super admin、tenant admin、空 visible 集场景的断言更新为目标契约；证明
  `action=visible` 不调用 action-map，`action=use` 只调用 `["use"]` 做筛选且没有最终五动作装饰，所有返回行
  只有 `visible`；保持 cursor、has_more 和资源集合断言。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-14
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_list_visible_first.py`
  **依赖**: 无

- [x] **T002**: imperative lazy action hook 单元测试
  **文件**: `src/frontend/platform/src/test/f051LazyResourceActions.test.tsx`
  **逻辑**: 覆盖初始 render 零请求、显式 load 后单请求、请求中去重、60 秒缓存、不同资源隔离、用户隔离、
  服务端失败状态，以及管理员不走前端全动作伪造分支。
  **覆盖 AC**: AC-05, AC-06, AC-09, AC-10, AC-12
  **验证**: `cd src/frontend && pnpm --filter bisheng test -- f051LazyResourceActions`
  **依赖**: 无

### Wave 2：最小后端响应与共享懒加载能力

- [x] **T003**: 知识库列表只装饰 visible
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`
  **逻辑**: 保留 visible IDs 枚举和请求 action 的候选过滤；删除返回页 `_KNOWLEDGE_LIST_ACTIONS` 查询，
  为最终返回行显式传入只含 `visible` 的 action map；管理员返回相同最小形态；不全局改变转换函数默认语义。
  **测试**: T001 全部通过；`test/permission/test_f048_list_action_cost.py` 保持通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-13, AC-14
  **依赖**: T001

- [x] **T004**: 共享懒加载 actions hook
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/useResourceActions.ts`
  **逻辑**: 在不改变既有 eager hook 消费者的前提下新增 named-export `useLazyResourceActions`；显式
  `load(resourceId)` 才复用现有 `user + resource type + resource id` TTL cache 与 in-flight Promise；结果和
  loading/error 按资源归属；lazy 路径不使用前端 admin shortcut。
  **测试**: T002 全部通过。
  **覆盖 AC**: AC-05, AC-06, AC-09, AC-10, AC-11, AC-12
  **依赖**: T002

### Wave 3：文档库与 QA 库菜单接入

- [x] **T005**: 知识库菜单懒加载组件回归测试
  **文件**: `src/frontend/platform/src/test/f051KnowledgeListLazyActions.test.tsx`
  **逻辑**: 对文档库和 QA 库建立相同断言：列表 render 不查询；可见普通行保留三点入口；打开后显示
  loading；成功仅显示授权的设置/删除/权限管理；复制独立；失败不显示权限项并提示；处理中行不查询；
  快速 A→B 不串 actions；关闭加载中菜单不自动重开。
  **覆盖 AC**: AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-15
  **依赖**: T004

- [x] **T006**: 菜单懒加载三语言状态文案
  **文件**: `src/frontend/platform/public/locales/zh-Hans/permission.json`,
  `src/frontend/platform/public/locales/en-US/permission.json`,
  `src/frontend/platform/public/locales/ja/permission.json`
  **逻辑**: 在 permission namespace 增加知识库行操作的 loading 与 no-available-actions 文案，三语言 key
  完全一致；权限失败复用既有 `error.checkFailed`，不新增重复文案。
  **覆盖 AC**: AC-06, AC-07, AC-10
  **依赖**: T004

- [x] **T007**: 文档库与 QA 库三点菜单按需加载
  **文件**: `src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`,
  `src/frontend/platform/src/pages/KnowledgePage/KnowledgeQa.tsx`
  **逻辑**: 所有可见普通行保留操作列/三点触发器；打开时调用 T004 hook；加载中和空动作显示 T006
  的只读状态；菜单项由当前行 lazy actions 决定；复制继续使用
  `create_knowledge + visible + Published`；busy 状态保持；请求失败关闭当前菜单并提示；不直接调用 HTTP。
  **测试**: T005 全部通过。
  **覆盖 AC**: AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-15
  **依赖**: T003, T004, T005, T006

### Wave 4：端到端与质量门禁

- [x] **T008**: E2E、性能结构断言和工程质量验证
  **文件**: 本 feature 的测试文件与 `tasks.md` 状态/偏差记录
  **逻辑**: 执行后端 focused tests、platform focused tests、lint/typecheck/i18n、arch-guard、diff-check；按
  design §7.3 验证 `/filelib` 文档/QA、仅 visible/edit/manage_permission/admin、权限失败、快速切换、
  `action=use` 选择器；确认列表首屏零 `my-permissions`，打开一行最多一个 in-flight 请求，后端 visible
  列表零最终五动作 BatchCheck。不可用的 live 环境必须单独报告，不能把未执行写成通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15
  **依赖**: T003, T007

---

## AC 追溯矩阵

| AC | Tasks |
|---|---|
| AC-01 | T001, T003, T008 |
| AC-02 | T001, T003, T008 |
| AC-03 | T001, T003, T008 |
| AC-04 | T001, T003, T008 |
| AC-05 | T002, T004, T005, T007, T008 |
| AC-06 | T002, T004, T005, T006, T007, T008 |
| AC-07 | T005, T006, T007, T008 |
| AC-08 | T005, T007, T008 |
| AC-09 | T002, T004, T005, T007, T008 |
| AC-10 | T002, T004, T005, T006, T007, T008 |
| AC-11 | T004, T005, T007, T008 |
| AC-12 | T002, T004, T007, T008 |
| AC-13 | T003, T008 |
| AC-14 | T001, T003, T008 |
| AC-15 | T005, T007, T008 |

---

## 实际偏差记录

> 推翻已确认的 spec/design 决策必须先停下重新确认；纯实现细节直接更新 design 并在此留一行指针。

- 暂无。

## 验证记录

- 后端 focused tests：14 passed；F051 E2E 用例已生成并完成本地收集，因未指定专用部署环境而 4 skipped。
- 前端 focused tests：13 passed；platform lint、arch-guard、diff-check 通过；三语新增 key 已逐文件校验。
- 全量 typecheck 仍有 2 个 beta1 基线错误，位于 `f048DashboardPermissions.test.tsx` 与
  `routeFilterPurity.test.ts`；`check-i18n` 仍被 beta1 既有 backend code `10992` 缺少 api_errors 文案阻断，
  均不在 F051 修改范围。
- live UI/API 步骤见 [e2e-checklist.md](./e2e-checklist.md)，部署专用环境后执行，不把本地 skip 记为通过。
