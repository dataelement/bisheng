# F115：执行状态

| 文档/阶段 | 状态 | 说明 |
|---|---|---|
| Spec Discovery | ✅ 已确认 | 2026-11-02，本会话 |
| spec.md | ✅ 已评审 | sdd-review 通过，用户于 2026-11-02 确认 |
| design.md | ✅ 已评审 | 2026-11-02 用户指示“开始开发” |
| tasks.md | ✅ 已拆解 | 对照 tasks-checklist 审查通过，按以下顺序执行 |
| 实现、测试与交付 | ✅ 本地实现与审查完成 | 部署 E2E、页面实机及双库验证仍待执行；未合并或部署 |

## 实施任务

所有路径相对仓库根。先写配对测试并运行观察失败，再实现并运行通过；不对其他工作区改动执行提交、恢复或覆盖。

- [x] **T01 后端 API 测试**：`src/backend/test/app_template/test_template_api.py`，本地 FastAPI + httpx、真实 SQLite 与租户事件、替换身份/授权外部端口；根/A/B 三租户参数化验证列表详情、普通用户拒写、管理员增改删、伪造归属、来源、助手快照、重名与报告资产。覆盖 AC: AC-01–13。
- [x] **T02 后端输入与仓储**：新建 `src/backend/bisheng/app_template/domain/schemas/template.py`、`repositories/template_repository.py`；独立异步会话 + strict_tenant_filter，创建只从来源读取快照，查询/重名/排序限定当前租户；支持 5/10 类型，不迁移旧数据。依赖 T01。
- [x] **T03 后端服务与 API**：新建 `app_template/domain/services/template_service.py`，修改 `api/v1/skillcenter.py`；使用权限应用身份与 visible 动作，薄接口，复用既有错误与返回形状。依赖 T02。
- [x] **T04 管理视图边界**：修改 `common/middleware/admin_scope.py` 与前端 `controllers/managementScope.ts`；模板读写进入管理视图，写入校验 X-Management-Tenant。配对边界测试归 T01 和 T06。依赖 T03。
- [x] **T05 报告文档授权**：修改 `api/services/report_template.py`，模板资产 fallback 改走模板 Service 严格查询；不改变源工作流合法授权。使用 T01 同租户/其他租户报告 key 测试。依赖 T03。
- [x] **T06 前端能力测试与 helper**：新增 `src/frontend/platform/src/test/appTemplatePermissions.test.tsx`、`pages/BuildPage/templatePermissions.ts`；管理员/部门管理员/创建应用普通用户矩阵、两种卡片入口、管理页直接访问与类型切换、管理写范围。覆盖 AC: AC-01–07、AC-11–12。
- [x] **T07 模板管理入口**：修改 platform 的 `pages/BuildPage/apps.tsx` 与 `components/bs-comp/cardComponent/index.tsx`；独立模板能力参数不改变其他管理员菜单。依赖 T06。
- [x] **T08 管理页与新增弹窗**：修改 `pages/BuildPage/appTemps.tsx`、`CreateTemp.tsx`；无权限不加载，租户切换重置数据，新增失败不假报成功、校验错误直接返回、阻止重复提交。调整既有 `test/listSorting.test.tsx` 的已认证管理员上下文。依赖 T06。
- [x] **T09 助手使用测试与编排**：新增 `test/assistantTemplate.test.ts`、`pages/BuildPage/assistantTemplate.ts`；白名单配置、默认模型、空资源引用、长提示词、保存失败复用已创建草稿。覆盖 AC: AC-04、AC-08、AC-13。
- [x] **T10 创建页面接入**：修改 `pages/BuildPage/CreateApp.tsx` 与 `hook.ts`；正确按类型读取、深拷贝快照、助手创建保存、异步读取及租户变化取消旧结果。依赖 T09、T08。
- [x] **T11 端到端与回归**：按 `/e2e-test` 自由模式运行 API 端到端并产出页面手动验证清单；运行后端模板/管理范围/报告模板测试，前端新增及排序/卡片/路由回归，lint/typecheck、arch-guard。记录真实环境缺口。依赖 T04–T10。
- [x] **T12 特性审查**：执行 `/sdd-code-review`；独立 reviewer 审查本特性 diff（不包含其他未提交文件），修复确认的问题、更新设计现状与验证证据。依赖 T11。

## 执行规则与验收命令

- 后端：`cd src/backend && uv run pytest test/app_template/`。
- 前端：`cd src/frontend/platform && pnpm test src/test/appTemplatePermissions.test.tsx src/test/assistantTemplate.test.ts src/test/listSorting.test.tsx src/test/hostedAppMenuTrim.test.tsx src/test/resolveRoutePermissions.test.ts`。
- 质量门禁：`cd src/frontend && pnpm lint && pnpm typecheck`；仓库根运行 `scripts/arch-guard.sh`（按脚本实际用法限定变更文件）。
- 不执行合并、部署或删除历史数据；是否提交由最终交付状态决定，不包含其他人的修改。

## 任务审查

LGTM。AC-01–13 均有配对测试；后端测试在实现前；前端只改 platform；无 Worker、DDL、新配置或新错误码；Service/Repository 分层与权限应用协议明确，范围和失败路径可验证。

## 实际偏差记录

- Git 已存在 feat/3.0.0 分支，Git 不允许同时创建 feat/3.0.0/115-* 子路径，使用 codex/115-app-template-tenancy；基于 release，尚未提交或合并。
- 工作区已有其他改动，本特性仅编辑本任务记录的文档与代码路径，不接管其他改动。

## 本地验证与发布前待办

- 后端精准回归 71 passed；前端相关 41 passed；Ruff、全前端 lint、arch-guard 无 VIOLATION，git diff --check 通过。
- 独立七维审查的两项问题均已修复并复核：助手错租户创建、历史长描述排序。详见 code-review.md 与 task-review.md。
- 全量前端 67 failed / 1482 passed，4 unhandled errors；typecheck 当前被其他并发 AssistantSetting.tsx:58 TS2322 阻断。没有将全量检查标为通过。
- 部署 E2E 用例已生成、执行后 5 skipped；本地替换外部身份/权限端口的 HTTP 测试不等同部署 E2E。详见 e2e-report.md。
- [ ] 提供已部署服务和专用租户账号后，执行真实 HTTP E2E 与页面清单。
- [ ] 发布前中央回归验证 MySQL/DM8/OpenFGA/MinIO。
- [ ] 在处理既有全量检查问题后，完成发布线集成验证；本次未提交、合并、推送或部署。

## 实施补充与审查修复

- T08 排序改为只提交 order_num，避免历史模板名称/描述受新输入限制影响，见 design §5。
- T10 扩及 api/v1/assistant.py（删除显式 JWT tenant 归属）、AppTempSheet.tsx（每次打开刷新与旧请求失效）、controllers/API/assistant.ts（UUID/可编辑输入类型）、新增 createAppTemplate.test.tsx；均服务既定 AC，不增加产品范围。
- 新包的 __init__.py 已补齐；未改模板表或初始化数据。
- 命令适配：uv 缓存目录受沙箱限制，使用现有 .venv/bin/pytest 和 ruff；未安装依赖或改运行配置。
