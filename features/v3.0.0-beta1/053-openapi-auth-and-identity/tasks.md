# Tasks: 开放 API 鉴权与身份传递（F053）

**关联**: [spec.md](./spec.md)（范围裁定 + 补充 AC；主体 AC = PRD v2.4 §五）· [design.md](./design.md)（§4 工作流分工是本文骨架；§6 共享契约是所有任务的对齐点）· [reference/vibe-049-tasks.md](./reference/vibe-049-tasks.md)（vibe 已拆的 T001–T076，本文按 id 引用其中未完成部分、只写 beta1 差异）
**版本**: v3.0.0-beta1
**代码事实口径**: `feat/3.0.0-beta1` @ `972397fbe`（2026-08-31）；vibe 侧 `3.0-vibe`。路径以 `src/backend/bisheng/` 为根；`platform/` = `src/frontend/platform/src/`，`client/` = `src/frontend/client/src/`。行号会漂移，符号名不会。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 2026-08-31 范围裁定 S1–S7 随 design ★ 一并确认；主体 AC 以 PRD v2.4 §五为准 |
| design.md | ✅ 已评审 | 2026-08-31 `/sdd-review design` 一轮 9 处修订就地吸收，同日 ★ 用户确认 |
| tasks.md | ✅ 已拆解 | 2026-08-31 按 WS-A～G 拆解；同日 `/sdd-review tasks` 一轮：拆分 5 个过大任务（C07 / F01 / D05 / D07 / B05）、补 AC-S2 / AC-21 / AC-22 覆盖、E2E 任务 AC 逐条列举、去 G04 的 TODO、补 5 处回滚说明、Beat 清理写明跨租户批量删除口径；Test-First「测试 + 实现合一」为有意偏离（见开发模式） |
| 实现 | 🔲 未开始 | 0 / 73 |

---

## 开发模式

- **分支**：集成分支 `feat/v3.0.0-beta1/053-openapi-auth-and-identity`（从 `feat/3.0.0-beta1` 拉）；每个工作流从集成分支拉 `feat/v3.0.0-beta1/053-ws-<a..g>-<name>`，完成后 PR 回集成分支；集成分支按 design §4 里程碑 M1–M4 合回 `feat/3.0.0-beta1`。**WS-A 与 WS-C 不得分别合回 beta1**（design §1 发版约束）。
- **并行前提**：WS-A 的 A01–A04（Wave 1 移植，约 2 天）先合入集成分支 → 其余工作流从此点起分支。各工作流只通过 design §6 契约耦合；**需要改 §6 契约时先改 design、再通知集成分支维护者**，不在任务里私改。
- **Alembic 链**：各 WS 的 revision 开发期 `down_revision` 指向从集成分支拉出时的 head；合入时由集成分支维护者串链（design §7）。
- **后端 Test-First（本文形态）**：为把任务数控制在可领取的量级（73 而非 140+），后端任务把「测试 + 实现」合为一个任务，但**每个任务的 `文件` 段先列测试文件、`逻辑` 段以测试用例开头**；执行者必须先把测试写成红、再写实现——`/task-review` 按此顺序检查。这是对清单「测试任务独立先行」的有意偏离，理由如上。每个任务写明配对测试文件；测试放 `src/backend/test/open_api/` 等 `test/<module>/`（不放根），`asyncio_mode=auto`。集成测试连 test 中间件（MySQL / Redis / OpenFGA）在 CI 跑；DM8 在 105 回归。`/api/v2/**` 断言**真 HTTP 状态**，`/api/v1/**` 管理端点断言**信封 `status_code`**。
- **前端**：platform 任务附「手动验证」步骤；client 任务同；新增 i18n key 三语同 PR；`react-query` 在 platform 冻结（vibe 坑 24）；不引入新 UI / 状态库。
- **vibe 任务引用**：写作 `≡ vibe T0xx`，表示逻辑 / 文件 / 测试口径沿用 `reference/vibe-049-tasks.md` 该任务，本文只列 beta1 差异；差异为空则写「无差异」。
- **每个任务**：`文件` / `逻辑` / `依赖` / `覆盖 AC`（PRD AC 用 `AC-n` / `AC-Pn`；spec 补充 AC 用 `AC-S/G/C/D/E/F-n`；vibe spec AC 用 `vibe-AC-nn`）。**PRD AC-49**（持 `delegate` 的密钥接本地开发三面被拒）在 beta1 **不适用**——三面不存在，其对应约束由 AC-S2（三扩展位不可签发）与 AC-48（互斥）承接。
- **跨 Feature 副作用登记**（release-contract 表 4）：A01（`user` 表加列）· A08 / A10（`open_endpoints` 与 `api/router.py`）· A14–A16（F048 runtime 回授分支）· A18（`tenant_reconcile` / `quota_service`）· C08（`message_session` / `chat_message` 加列 + DAO 参数）· C10（`knowledge_space_chat_service` 两分支）· D06（`user/api/user.py` / `user_tenant_sync_service` 触发点）· E03（`workstation/domain/services/chat_service.py` 抽 service）· G01（`share_link`）。

---

## Tasks

### WS-A · 底座移植 + 存量端点接入（后端 · 7～8 人天 · 里程碑 M1 → M2）

#### A-Wave 1 · 移植（M1，其余工作流的起点）

- [ ] **A01**: cherry-pick vibe 5 提交 + 解冲突
  **文件**: 全部（85 文件，见 discovery §2.1）；冲突点：`packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（合并两侧新增 key，然后**重跑生成脚本**产出 `platform/public/locales/*/api_errors.json` 与 `client/src/locales/*/api_errors.gen.json`，不手改）、`api/v1/endpoints.py get_env`（保留两侧新增字段）、`test/permission/test_f048_schema_contract.py`（合并 `user_type` 列断言）
  **逻辑**: 顺序 `a15f06135 → 86e52f90b → 43e73bfc5 → c5989ffd6 → e31c35732`；**不搬** `features/v3.0.0/049-*`（`git checkout` 时剔除）；`docs/constitution.md` C5 表的 260 段改动要搬。移植后 `pnpm lint && pnpm typecheck`（`src/frontend/`）、`ruff`、arch-guard 全绿；`test/open_api/` 8 个文件全绿。
  **依赖**: 无
  **覆盖 AC**: AC-1 · AC-2 · AC-3 · AC-4 · AC-5 · AC-14 · AC-15 · AC-17 · AC-21 · AC-22（回归 vibe 已实现部分）

- [ ] **A02**: Alembic：`api_credential` / `service_account` 建表 + `user_type` revision 接链
  **文件**: `core/database/alembic/versions/v3_0_0b1_f053_api_credential_tables.py`（新）；`versions/v3_0_0_f049_user_user_type.py`（改 `down_revision` 指向 beta1 当前 head，**文件名与 revision id 不改**，design §7）
  **逻辑**: 只 DDL（两表 + 索引 + `token_hash` unique；`VARCHAR` 不 `CHAR`；`scopes` 用 `JsonType`）；`downgrade` 删表前 dump `api_credential`（撤销记录是审计资产）。`alembic upgrade head` 在空库与 beta1 存量库各跑一次。
  **依赖**: A01
  **覆盖 AC**: AC-27（升级零数据迁移的前提）

- [ ] **A03**: 主体解析与前缀提取按 `subject_kind` 参数化
  **文件**: `open_api/domain/services/credential_validator.py`（bearer 提取接受 `bs-sak-` / `bs-pat-` 两前缀，按前缀映射 `subject_kind` 预期并与行上 `subject_kind` 比对）、`credential_service.py`（`issue(subject_kind, …)` 按 kind 选前缀）、`domain/models/api_credential.py`（`revoke_reason` 常量增 `regenerated`）；测试 `test/open_api/test_credential_validator.py` 增前缀 / kind 不匹配用例
  **逻辑**: PRD 附录 E.6 两处约 5 行；`SUBJECT_RESOLVERS` 仍只注册 `service_account`（`natural_person` 由 D01 注册）；未注册 kind → `26002`。
  **依赖**: A01
  **覆盖 AC**: AC-P3（前提）· vibe-AC-02

- [ ] **A04**: `@open_api_scope` 标记签名扩展 + `OpenApiPrincipal` 扩字段 + `conn.scope` 双写
  **文件**: `open_api/domain/scopes.py`（`modes=("S","D")`, `session=False`, `allow_share_token=False`, `idempotent=False`）、`open_api/domain/context.py`（增 `tenant_id / mode / effective_user_id / on_behalf_of_user_id / end_user_id`，design §6.1）、`open_api/api/dependencies.py`（写 ContextVar 同时 `conn.scope["open_api_principal"] = principal`；身份头存在 → `26004`，WS-A 期形态）；测试 `test/open_api/test_scopes.py`、`test_dependencies.py`
  **逻辑**: 这是其余工作流的接口，A-Wave 1 内必须定稿；`whoami` 响应增 `subject_kind` 与 `mode`。
  **依赖**: A01
  **覆盖 AC**: AC-32（模式 S 缺省）· vibe-AC-33（WS-A 期任何身份头 403）

#### A-Wave 2 · 存量端点接入 + 缺陷修复 + 配置移除（≡ vibe Wave 3）

- [ ] **A05**: v2 路由完整性 + 全端点鉴权矩阵测试 ≡ vibe T034
  **差异**: 端点总数按 beta1 重数（43 HTTP + 2 WS，多出的 1 个补进 `OPEN_API_SCOPES` 映射并回写 PRD 附录 B.1）；矩阵增「`modes` 声明存在」断言（每个端点标记必须含 `modes`）；增「`open_platform.enabled=false` 时 `GET /scopes` 不含三扩展位、以三位入参签发 → `26023`」用例。
  **依赖**: A04
  **覆盖 AC**: AC-1 · AC-29（vibe-AC-29）· AC-S1 · AC-S2

- [ ] **A06**: `resolve_operator` 收紧 + `get_open_api_login_user` ≡ vibe T035 / T036
  **差异**: 无（`get_default_operator*` 删除、`resolve_operator` 保留到 WS-C C09 删除；死函数 `get_knowledge_space_chat_service_for_openapi` 一并删）。
  **依赖**: A04
  **覆盖 AC**: AC-26（前置）· vibe-AC-39

- [ ] **A07**: 标记接入：`knowledge.py` + `citation.py` + `llm.py` ≡ vibe T037
  **差异**: 一次填满四个参数——`llm/workbench/asr` / `tts` 标 `modes=("S",)`；其余 `("S","D")`；`session` 全 False。
  **依赖**: A05
  **覆盖 AC**: AC-S1

- [ ] **A08**: 标记接入：`filelib.py` ≡ vibe T038
  **差异**: `download_statistic` 标 `modes=("S",)`；`add_qa` 标 `idempotent=True`（WS-F 消费）；四处裸 `user_id` 端点本任务**不动参数**（C09 收口）。
  **依赖**: A05
  **覆盖 AC**: AC-S1

- [ ] **A09**: 标记接入：`workflow.py` + `flow.py` + `assistant.py`（HTTP + WS）≡ vibe T039
  **差异**: `workflow/invoke` 标 `session=True, idempotent=True`；两个 WS 与 `assistant/chat/completions` 标 `session=True, allow_share_token=True`（WS-G 消费）。
  **依赖**: A05
  **覆盖 AC**: AC-S1 · AC-18（前置）

- [ ] **A10**: `chat.py` 删除 + `router_rpc` 挂全局依赖 ≡ vibe T040
  **差异**: 无。
  **依赖**: A07 · A08 · A09
  **覆盖 AC**: AC-1 · vibe-AC-30（6 端点 404）

- [ ] **A11**: 四处既有缺陷（未上线守卫 / stop 归属 / `download_statistic` 收口 / 助手 WS 裸崩）≡ vibe T041 / T042 / T043 + 坑 16
  **差异**: 助手 WS 裸崩修复（身份解析全部进依赖 + `WebSocketException(1008)`）在 vibe 归 T052，本文提前到本任务，因为 WS-G 只接 share-token 分支、不改 HTTP 密钥分支。
  **依赖**: A10
  **覆盖 AC**: AC-18 · AC-19 · AC-20 · vibe-AC-40

- [ ] **A12**: 升级零迁移 + `default_operator` / `enable_guest_access` 移除 + 文档修订 ≡ vibe T044 / T045
  **差异**: `docs/api/*.md` 的身份模式名称此处先用「自身身份模式」（D09 不必再改一遍）。
  **依赖**: A10
  **覆盖 AC**: AC-27 · AC-26（错误引导删除）

- [ ] **A13**: `open_api.call` 结构化日志行（WS-C 表化前的过渡）
  **文件**: `open_api/api/dependencies.py`（`_log_call` 已有，补 `mode / on_behalf_of / end_user` 三字段占位）
  **逻辑**: 日志行是 Redis / DB 故障时的兜底，C07b 表化后**保留**。
  **依赖**: A04
  **覆盖 AC**: AC-23（兜底通道）

#### A-Wave 3 · 资源归属人回授 + 主体侧授权后端（≡ vibe Wave 5 后端部分）

- [ ] **A14**: F048 runtime 回授分支 + 新来源值 `SERVICE_ACCOUNT_AUTOGRANT` ≡ vibe T057 / T058 / T059
  **差异**: `authorize_created(autogrant_user_id=…)` 增一条前置：`principal.mode == 'D'` 时业务侧传 `None`（C04 消费；本任务只保证参数可空且 INHERIT 目标忽略）。
  **依赖**: A04
  **覆盖 AC**: AC-42 · AC-44 · AC-47

- [ ] **A15**: 资源归属人三条创建路径（知识库 / 知识空间 / 文件）≡ vibe T060 / T061 / T062
  **差异**: 硬写处参数化时用 `principal.effective_user_id` 作 owner 缺省（模式 S = 服务账号 → 再换归属人；模式 D 由 C04 直接落目标），避免 C04 再改一遍同一行。
  **依赖**: A14
  **覆盖 AC**: AC-42 · AC-43 · AC-45 · AC-46（前置）

- [ ] **A16**: 主体反查 `subject_api.list_subject_grants` + 授权端点 + 删除流程升级 ≡ vibe T063 / T064 / T065
  **差异**: 无。
  **依赖**: A14
  **覆盖 AC**: AC-28 · AC-29 · AC-30 · AC-31 · AC-47

#### A-Wave 4 · 对账 / 配额 / 管理接口矩阵 / 到期 Beat / 发布说明（≡ vibe Wave 6）

- [ ] **A17**: 对账豁免 + 配额排除 ≡ vibe T068 / T069
  **差异**: 无。
  **依赖**: A01
  **覆盖 AC**: AC-16 · AC-17

- [ ] **A18**: 管理接口矩阵其余项 + 全局成员搜索纵深 ≡ vibe T070 / T071
  **差异**: 无。
  **依赖**: A01
  **覆盖 AC**: AC-14 · AC-15 · vibe-AC-20 · vibe-AC-22

- [ ] **A19**: 到期兜底 Beat `expire_credentials` ≡ vibe T072 / T073
  **差异**: 同一 worker 模块 `worker/open_api/tasks.py` 预留 C07 的清理任务入口（同文件、不同函数）。
  **依赖**: A01
  **覆盖 AC**: vibe-AC-05 · vibe-AC-12

- [ ] **A20**: 发布说明「升级前必读」+ secret scanning 前缀规则 ≡ vibe T074
  **差异**: 增：`bs-pat-` 前缀规则；PAT 与技能包默认关闭的开启方式；`Idempotency-Key` / 限流响应头说明（WS-F 落地后补）。
  **依赖**: A12
  **覆盖 AC**: AC-26 · AC-27 · vibe-AC-50 / 54

- [ ] **A21**: WS-A E2E（`/e2e-test`）+ 114 手动验证 M1 / M2 前半 ≡ vibe T075
  **差异**: 手动清单按 design §9 M1 段。
  **依赖**: A05–A20
  **覆盖 AC**: AC-1 · AC-2 · AC-3 · AC-4 · AC-5 · AC-14 · AC-15 · AC-16 · AC-17 · AC-18 · AC-19 · AC-20 · AC-21 · AC-22 · AC-27 · AC-28 · AC-29 · AC-30 · AC-31 · AC-40 · AC-42 · AC-43 · AC-44 · AC-45 · AC-47 · AC-S1 · AC-S2

### WS-B · 管理界面（platform · 8～10 人天 · M1 起可开工，M3 完成）

- [ ] **B01**: 移植 8 个组件 + 系统设置 tab 挂载 + 视觉核对
  **文件**: `platform/pages/SystemPage/components/ServiceAccount/*`（随 A01 已到位）、`pages/SystemPage/index.tsx`、`controllers/API/serviceAccount.ts`、`types/api/serviceAccount.ts`、`public/locales/*/serviceAccount.json` ×3
  **逻辑**: A01 后跑 `pnpm lint:prune`；按 `packages/ui/docs/` 规范核对字体 / 色彩 / 圆角，视觉改动列清单交设计师确认，不自行改样式（design B1）。
  **手动验证**: 租户管理员登录 → 系统管理 → 服务账号 tab 可见；非管理员不可见；新建 → 直达签发 → 明文弹窗必须勾选才能关。
  **依赖**: A01
  **覆盖 AC**: AC-2 · AC-40 · AC-S2（表单不出现三扩展位）· vibe-AC-41 · vibe-AC-43 · vibe-AC-44

- [ ] **B02**: 「资源授权」tab + 删除弹窗升级 ≡ vibe T066 / T067
  **差异**: 无。
  **手动验证**: 授予 → 列表出现来源「管理员授予」；API 建库 → 出现「创建时自动回授」；「全部撤销」后回授项仍在；单条撤销回授项弹二次确认；名下有 `delegate` 密钥时顶部显著提示。
  **依赖**: A16
  **覆盖 AC**: AC-28 · AC-29 · AC-31 · AC-47 · vibe-AC-64

- [ ] **B03**: 签发 / 编辑表单「委托配置」分组
  **文件**: `ServiceAccount/KeyIssueDialog.tsx`（抽 `DelegateScopeSection.tsx`）、`components/bs-comp/selectComponent/DepartmentUsersSelect`（多选）+ 部门树多选（复用现有部门选择器）、`controllers/API/serviceAccount.ts`（`delegate_scope[]` 字段）、`serviceAccount.json` ×3
  **逻辑**: 勾 `delegate` 展开；范围为空 → 保存禁用 + 原因；与 toolkit 三位互斥 → 保存失败 + 文案；风险提示两条（design B3）；`GET /scopes` 未返回 `delegate` 位时整组隐藏（C 未合入时）。编辑与签发同组件。
  **手动验证**: 勾 delegate 不配范围 → 保存灰；配范围 + 勾 `app:manage`（开关开时）→ 保存报互斥；保存后列表「委托范围摘要」显示「销售部及下级 + 张三」。
  **依赖**: A01（组件）· C03（端点）
  **覆盖 AC**: AC-39 · AC-48 · AC-C2（前端侧）

- [ ] **B04**: 服务账号列表「委托」列 + 密钥列表「委托范围摘要」列
  **文件**: `ServiceAccountList.tsx`、`ApiKeysTab.tsx`
  **依赖**: C03
  **覆盖 AC**: PRD §4.7.1 / §4.7.3 列定义

- [ ] **B05a**: 「个人访问令牌」tab 骨架 + API 封装 + 台账表 + 吊销
  **文件**: `pages/SystemPage/components/PersonalToken/{PersonalTokenPanel,PersonalTokenLedger}.tsx`（新）、`pages/SystemPage/index.tsx`（同级 tab，`isSuperAdmin ∪ isChildAdmin`）、`controllers/API/personalToken.ts`（新）+ `types/api/personalToken.ts`、`public/locales/*/personalToken.json` ×3
  **逻辑**: 台账列（持有人 / 掩码 / 创建 / 最后使用 / 有效期 / 权限位 / 管理员高亮）；单个 + 按人吊销（二次确认）。
  **手动验证**: 台账只见掩码；吊销 → 员工端状态变「已吊销（管理员）」。
  **依赖**: D05b（端点）
  **覆盖 AC**: AC-P11 · AC-P12（不显示明文）

- [ ] **B05b**: 租户开关 + 默认 TTL 设置卡
  **文件**: `pages/SystemPage/components/PersonalToken/PatSettingsCard.tsx`（新）、`contexts/locationContext.tsx`（`patDeployEnabled` 自 `GET /env`）
  **逻辑**: 部署级未开 → 置灰 + 说明文案指向运维（config.yaml `open_api.pat_enabled`）；单租户部署（`!multiTenantEnabled`）只显示租户级开关；TTL 天数输入（默认 365）。
  **手动验证**: 部署级关 → 开关灰 + 提示；开后切租户开关 → 员工端立即可领。
  **依赖**: B05a
  **覆盖 AC**: AC-P1b · AC-P2a（前端）

- [ ] **B06**: 签发 / 编辑表单「网络」分组（IP 白名单 / 限流 / 日配额）
  **文件**: `KeyIssueDialog.tsx`（`NetworkSection.tsx`）、`ApiKeysTab.tsx`（列显示）、`serviceAccount.ts`
  **逻辑**: CIDR 多行校验（前端做格式预检，后端为准）；留空 = 不限。
  **依赖**: F01b
  **覆盖 AC**: AC-24（前端配置面）· AC-F4

- [ ] **B07**: 审计页 lockstep + `ApiAccess*` 示例 + `ChatLink` 免登录 URL ≡ vibe T032 前端半 / T046 / T054 前端半
  **文件**: `controllers/API/log.ts`（`actions` / `getModulesApi` 加 `open_api.*` 含 `open_api.pat.*`）、`public/locales/*/bs.json`（`log.eventTypeEnum` 三语）、`components/bs-comp/apiComponent/{ApiAccess,ApiAccessFlow,ChatLink}.tsx`（示例 `bs-sak-…`、身份模式名「自身身份 / 代表他人」、免登录 URL 带 `share_token`）
  **逻辑**: `ApiAccessFlow.tsx` 冻结 188 条中文——改动即整文件 i18n 偿债（`/i18n-localizer`），单列工时。
  **依赖**: A01 · G05（URL）
  **覆盖 AC**: AC-P22（前端侧）· vibe-AC-54

### WS-C · 身份传递（后端 · 12～14 人天 · M2 必需）

- [ ] **C01**: 错误码 26005–26007 / 26010 / 26016 / 26018 / 26019 + 26004 语义收窄 + 三语
  **文件**: `common/errcode/open_api.py`、`packages/locales/src/api_errors/*.json` ×3 → 跑生成脚本、`docs/constitution.md` C5 表
  **逻辑**: 全部继承 `OpenApiAuthError` 带真 HTTP 状态（design 坑 16）；`26005` 文案对四情形一致。
  **依赖**: A01
  **覆盖 AC**: AC-6 · AC-7 · AC-8 · AC-10 · AC-38 · AC-C1 · AC-C3

- [ ] **C02**: Alembic：`api_credential_delegate_scope` + `message_session.external_user_id` + `chat_message.external_user_id`
  **文件**: `core/database/alembic/versions/v3_0_0b1_f053_delegate_scope_and_session_partition.py`（新）、`open_api/domain/models/credential_delegate_scope.py`（新）、`database/models/session.py` / `message.py`（列 + 索引）
  **回滚**: `downgrade()` 删表 + 删两列（列只写不读、删除无业务影响；委托范围表回滚前 dump 供审计）
  **依赖**: A02
  **覆盖 AC**: AC-9（存储前提）· AC-11（分区键前提）

- [ ] **C03**: 委托范围服务 + 密钥端点扩展（`delegate_scope[]`）+ 保存期校验 测试与实现
  **文件**: `open_api/domain/services/delegate_scope_service.py`（新：`replace_scope(credential, entries)`、`is_target_in_scope(credential_id, user_id)`——`user` 直查 + `department` 子树 `Department.path LIKE`）、`api/endpoints/service_account_keys.py`（签发 / 编辑接受 `delegate_scope`；勾 `delegate` 范围空 → 拒；`delegate` ⊗ 三扩展位 → 拒；PAT 主体 → 拒；去 `delegate` 同事务删范围）、`domain/scopes.py`（登记 `delegate` 位：`group='delegate'`、`endpoints=()`）；测试 `test/open_api/test_delegate_scope.py`
  **逻辑**: `user` 条目保存期校验 `user_type=='human'`（`26021` 同族）；范围摘要字段（`scope_summary`）供列表。
  **依赖**: C01 · C02
  **覆盖 AC**: AC-9 · AC-37 · AC-39 · AC-48 · AC-C2 · AC-P4（`delegate` 对 PAT 拒）

- [ ] **C04**: `identity_service`：身份头解析 + 模式分流 + 五道准入 + 目标身份构造 测试与实现
  **文件**: `open_api/domain/services/identity_service.py`（新：`resolve_identity(principal, headers, marker) -> ResolvedIdentity`）、`api/dependencies.py`（槽位 ⑦ 接入，替换 WS-A 期「任何身份头 403」）、`open_api/domain/context.py`（填 `mode / effective_user_id / on_behalf_of_user_id / end_user_id`）；测试 `test/open_api/test_identity_modes.py`（五道准入逐条、`26005` 四情形响应体逐字节相等 + 耗时同量级、`26007` 按租户两套用例、PAT + OBO、两头并存、End-User 超限、持 `delegate` 漏头无业务数据）
  **逻辑**: design C1 / C3；检查 3 复用 `_check_is_global_super` + `is_tenant_admin`；目标 `UserPayload` 角色取全、`is_global_super=False`；WS 握手期同一函数。
  **依赖**: C03
  **覆盖 AC**: AC-6 · AC-7 · AC-8 · AC-10 · AC-11 · AC-38 · AC-41 · AC-P15 · AC-C1

- [ ] **C05**: 模式 D 归属：会话归目标 + 创建资源 owner=目标且不回授 测试与实现
  **文件**: A15 参数化处按 `principal.mode` 分支（`autogrant_user_id=None`）；`open_endpoints/api/endpoints/{workflow,assistant}.py` 会话创建处 `user_id = effective_user_id`；测试 `test/open_api/test_mode_d_ownership.py`
  **依赖**: A15 · C04
  **覆盖 AC**: AC-32（会话回工作台的后端半）· AC-46 · AC-C4

- [ ] **C06**: 分区键写入 + DAO 参数（只写不读）
  **文件**: `database/models/session.py`（`filter_session / afilter_session / filter_session_count` 增 `external_user_id: str | None = None`）、`MessageSessionDao.insert_one` 路径写 `principal.end_user_id`；`chat_message` 冗余双写；`session=True` 端点缺省 WARN 日志
  **依赖**: C02 · C04
  **覆盖 AC**: AC-11（分区键）· AC-43（模式 S 会话不进归属人列表：`user_id` 仍是服务账号）

- [ ] **C07a**: 逐调用审计：Alembic + 模型 + DAO（基础设施）
  **文件**: `core/database/alembic/versions/v3_0_0b1_f053_open_api_call_log.py`（新）、`open_api/domain/models/open_api_call_log.py`（新：字段见 design §6.4；`OpenApiCallLogDao.abulk_insert(rows)` 单方法）、`core/config/open_platform.py`（`call_log_retention_days` 默认 90）
  **回滚**: `downgrade()` 删表（审计流水，回滚前 dump）
  **依赖**: C02
  **覆盖 AC**: AC-C5（存储前提）

- [ ] **C07b**: 审计队列 + flusher + ASGI 中间件 测试与实现
  **文件**: 测试 `test/open_api/test_call_audit.py`（模式 S / D / 被拒 401 / WS 建断连各一行且字段齐全；队列满丢弃并计数；flusher 抛错不影响请求；按租户分组写入后 `tenant_id` 正确）；`open_api/domain/services/call_audit_service.py`（新：`asyncio.Queue(10000)` + flusher 每 1s / 200 条，按 `tenant_id` 分组、每组 `set_current_tenant_id` 后 `abulk_insert`）、`open_api/api/middleware.py`（新：纯 ASGI，只挂 `/api/v2` 前缀，wrap `send` 取状态与耗时，读 `scope["open_api_principal"]`）、`main.py`（挂中间件 + lifespan 启停 flusher，退出前 flush）
  **依赖**: C04 · C07a
  **覆盖 AC**: AC-23 · AC-P13 · AC-C5

- [ ] **C07c**: 审计清理 Beat `purge_call_log`
  **文件**: 测试 `test/open_api/test_call_log_purge.py`；`worker/open_api/tasks.py`（`purge_call_log` 每日，A19 同模块）、`Settings.celery_task.beat_schedule` 缺省注入
  **逻辑（tenant_id）**: 清理按 `create_time < now - retention` **跨全部租户**批量 DELETE——在 `bypass_tenant_filter()` 下执行且显式说明：租户过滤只拦 SELECT（C3），本任务是唯一允许对该表批量删除的路径；不经 Celery headers 传 tenant_id（无单租户语义）。
  **依赖**: C07a
  **覆盖 AC**: AC-C5（保留期）

- [ ] **C08**: 两个 WS 握手期准入（模式 D + End-User）
  **文件**: `api/dependencies.py` WS 分支调 `identity_service`（头从握手 `scope["headers"]` 读）、`open_endpoints/api/endpoints/{workflow,assistant}.py` WS 会话归属按 `effective_user_id`
  **依赖**: C04 · A11
  **覆盖 AC**: AC-18（模式 D 形态）· vibe-050 AC-08

- [ ] **C09**: 裸 `user_id` 收口 + `resolve_operator` 删除 + `add_relative_qa` 死参数
  **文件**: `open_endpoints/api/endpoints/{filelib,assistant}.py`（6 端点：请求体 / 查询串出现 `user_id` → `26019`）、`open_endpoints/domain/utils.py`（删 `resolve_operator`）；测试 `test/open_api/test_bare_user_id_removed.py`
  **依赖**: C04
  **覆盖 AC**: AC-26 · AC-C3

- [ ] **C10**: `POST /filelib/retrieve` 文件级过滤 + 铁律 3 反向测试
  **文件**: `knowledge/domain/services/knowledge_space_chat_service.py`（`_aretrieve_chunks_for_kb` / `_aretrieve_chunks_for_knowledge_base` 接 `build_index_prefilter` + `post_filter_visible_files`，执行身份 = `effective_user`）；测试 `test/knowledge/test_openapi_retrieve_file_visibility.py`（正例集合相等 vs 工作台路径；反例无权文件名与正文不出现；mock 过滤器抛错 → 503 且 body 无 chunk）
  **逻辑**: design C6；文档知识库按库级。
  **依赖**: C04
  **覆盖 AC**: AC-12 · AC-13 · AC-P5 · AC-P6 · AC-P7（D 复用）

- [ ] **C11**: WS-C 集成测试矩阵 + E2E + 114 手动验证 M2 段
  **文件**: `test/open_api/test_identity_e2e.py`；`/e2e-test` 清单
  **依赖**: C01–C10
  **覆盖 AC**: AC-6 · AC-7 · AC-8 · AC-9 · AC-10 · AC-11 · AC-12 · AC-13 · AC-23 · AC-26 · AC-32 · AC-37 · AC-38 · AC-39 · AC-41 · AC-46 · AC-48 · AC-C1 · AC-C2 · AC-C3 · AC-C4 · AC-C5

### WS-D · 个人访问令牌（后端 + client · 12～15 人天 · M3）

- [ ] **D01**: 错误码 26040–26043 三语 + Settings（`pat_enabled` / `pat_admin_ttl_days`）+ `get_env` 透传
  **文件**: `common/errcode/open_api.py`、`packages/locales/src/api_errors/*.json` ×3、`core/config/open_platform.py`（`OpenApiConf` 增两键）、`api/v1/endpoints.py get_env`（`pat_deploy_enabled`、`pat_enabled`=部署 ∧ 租户）
  **依赖**: A01
  **覆盖 AC**: AC-P1 · AC-P1b（前提）

- [ ] **D02**: Alembic + 模型：`open_api_tenant_setting` + 租户级开关服务（Redis 60s 缓存 + 写时失效）
  **文件**: 测试 `test/open_api/test_pat_tenant_setting.py`；`core/database/alembic/versions/v3_0_0b1_f053_pat_tenant_setting.py`（新）、`open_api/domain/models/open_api_tenant_setting.py`（新）、`open_api/domain/services/personal_token_service.py`（`get_tenant_setting / update_tenant_setting`）
  **回滚**: `downgrade()` 删表（开关回落为「关」，与默认一致）
  **依赖**: A02 · D01
  **覆盖 AC**: AC-P1 · AC-P1a · AC-P2a · AC-D2

- [ ] **D03**: `natural_person` 解析器注册 + 管线槽位 ④ 能力开关 + 可见租户不放开 测试与实现
  **文件**: `open_api/domain/services/credential_validator.py`（`SUBJECT_RESOLVERS['natural_person']`：存在 / `delete==0` / `user_type=='human'` / 活跃租户 == 密钥租户 → 取角色 + `_check_is_global_super` 入缓存载荷；失败 `26043`；`_visible_tenant_ids` 对任何主体按密钥租户算）、`api/dependencies.py`（槽位 ④：两层开关任一关 → `26040`；PAT 携 OBO → `26004` 专用文案）；测试 `test/open_api/test_natural_person_resolver.py`（含超管 PAT 跨租户无结果且不泄露存在性）
  **依赖**: A03 · A04 · D02
  **覆盖 AC**: AC-P1 · AC-P8 · AC-P9 · AC-P14 · AC-P15 · AC-P16 · AC-P17 · AC-P17a

- [ ] **D04**: `personal_token_service`：一人一把 / 重新获取 / 删除 / 白名单 / TTL / 管理员警示 测试与实现
  **文件**: `open_api/domain/services/personal_token_service.py`（`obtain(user)` 先 `revoke(regenerated)` 再 `issue(kind='natural_person', scopes=['knowledge:read'], expires_at=now+ttl)`；`delete(user)`；`26041` / `26042`；`holder_is_admin` → `warn_admin_full_read` + `min(租户 TTL, admin TTL)`）；审计 `open_api.pat.{obtain,regenerate,delete}`（`audit_log.py` lockstep）；测试 `test/open_api/test_personal_token_service.py`
  **依赖**: D03
  **覆盖 AC**: AC-P2 · AC-P3 · AC-P4 · AC-P10 · AC-P17（警示）· AC-D1 · AC-D3

- [ ] **D05a**: 员工自助端点 `/api/v1/me/api-token` + 安装提示词 测试与实现
  **文件**: 测试 `test/open_api/test_personal_token_self_api.py`（明文只在 POST 出现一次；GET 无令牌返回 null；DELETE 后 3s 内 401；只能看自己的；提示词含请求的 `X-Forwarded-Host`）；`open_api/api/endpoints/personal_token_self.py`（新：GET / POST / DELETE / `GET install-prompt`——Base URL 取 `X-Forwarded-Proto/Host` 优先、回落 `request.base_url`）、`open_api/api/router.py`（挂 `/api/v1/me/api-token`）
  **依赖**: D04
  **覆盖 AC**: AC-P3 · AC-P10 · AC-P18

- [ ] **D05b**: 管理员端点 `/api/v1/personal-tokens` 测试与实现
  **文件**: 测试 `test/open_api/test_personal_token_admin_api.py`（台账无明文字段、含 `holder_is_admin`；非管理员 403 信封；跨租户列空；按人吊销 3s 内失效；部署级未开时 `PUT settings enabled=true` → 26040）；`open_api/api/endpoints/personal_token_admin.py`（新：台账分页 / `{id}/revoke` / `revoke-by-user/{uid}` / `GET|PUT settings`；门禁 `get_service_account_admin`；审计 `open_api.pat.{admin_revoke,setting_update}`）、`common/middleware/admin_scope.py`（`/api/v1/personal-tokens` 入 `MANAGEMENT_API_PREFIXES`）
  **依赖**: D04
  **覆盖 AC**: AC-P11 · AC-P12 · AC-P16 · AC-P1b（后端）

- [ ] **D06**: 级联失效三触发点 + 校验期兜底测试
  **文件**: `user/api/user.py`（`update_user_delete_hook` 置 `delete=1` 后调 `revoke_all_by_subject('natural_person', uid, 'subject_disabled')` + `invalidate_subject_cache`）、用户删除路径（`subject_deleted`）、`tenant/domain/services/user_tenant_sync_service.py sync_user`（租户变更 → `subject_disabled`）；测试 `test/open_api/test_pat_cascade.py`（三触发点各一例 + 「触发点漏掉、靠解析器兜底」一例断言 ≤ 5s）
  **依赖**: D04
  **覆盖 AC**: AC-P8 · AC-P9

- [ ] **D07a**: 技能包内容 `bisheng-knowledge-search`（静态文件）
  **文件**: `open_api/skill_packs/bisheng-knowledge-search/{SKILL.md,meta.json,SECURITY.md,references/api.md,scripts/bs_request.py}`（新；结构参照 `linsight/builtin_skills/bisheng-docx`；占位符 `{{BASE_URL}}` / `{{ALLOWED_HOSTS}}`）
  **逻辑**: SKILL.md 要点见 design D6：description 写足触发词（知识库 / 检索 / 搜一下有没有）；流程 = 先 `GET /api/v2/filelib/` 拿知识空间清单再 `POST /api/v2/filelib/retrieve`；凭据 `BISHENG_API_KEY` 环境变量优先、回落 `~/.bisheng/credentials.json`；401 / 403 / 429 分层处理；`api.md` 列端点全表 + 错误码 + 认证头。手动验证：贴给 Claude Code 能装、能按提示词触发。
  **依赖**: A01
  **覆盖 AC**: AC-P20 · AC-D4（仓内不含地址）

- [ ] **D07b**: zip 打包服务 + 匿名分发端点 测试与实现
  **文件**: 测试 `test/open_api/test_skill_pack.py`（zip 可解且含 5 文件；`SKILL.md` 中 Base URL = 请求实例地址；`SECURITY.md` 白名单 = 实例域名；两次下载字节一致）；`open_api/domain/services/skill_pack_service.py`（新：目录 → 内存 zip，`mtime=0`，渲染占位符）、`open_api/api/endpoints/skill_pack.py`（新：`GET /api/v1/open-api/skills/{pack}.zip` 匿名，`pack` 白名单校验防路径穿越）、`utils/http_middleware.py`（`TENANT_CHECK_EXEMPT_PATHS` 加 `/api/v1/open-api/skills`）
  **依赖**: D07a · D05a（提示词端点引用本路径）
  **覆盖 AC**: AC-P18 · AC-P19 · AC-D4

- [ ] **D08**: client 个人中心「API 令牌」弹窗
  **文件**: `client/layouts/UserPopMenu.tsx`（菜单项，`env.pat_enabled` 为真才渲染）、`client/components/PersonalTokenDialog.tsx`（新：获取 / 状态 / 删除·重新获取 / 明文一次性 + 「已保存」勾选 / 安装提示词复制 / curl 示例）、`client/api/personalToken.ts`（新，走 `~/api` 封装）、`client/locales/{zh-Hans,en,ja}/*.json`
  **手动验证**: 开关关 → 无菜单项；开 → 获取 → 明文一次 → 关闭后只见掩码；重新获取 → 旧的 3s 内 401；复制提示词贴给 Claude Code → 能装包并检索。
  **依赖**: D05a · D07b
  **覆盖 AC**: AC-P2 · AC-P3 · AC-P10 · AC-P18 · AC-P21（链路端到端）

- [ ] **D09**: 对客文档改名「自身身份模式」+ 错误码表处置列 + PAT 接入章节
  **文件**: `docs/api/*.md`（A12 已改名则本任务只补 PAT 章节与 260 段错误码表）
  **依赖**: A12
  **覆盖 AC**: AC-P22

- [ ] **D10**: WS-D 集成测试矩阵 + E2E + 114 手动验证 M3 段
  **依赖**: D01–D09 · C10
  **覆盖 AC**: AC-P1 · AC-P1a · AC-P1b · AC-P2 · AC-P2a · AC-P3 · AC-P4 · AC-P5 · AC-P6 · AC-P7 · AC-P8 · AC-P9 · AC-P10 · AC-P11 · AC-P12 · AC-P13 · AC-P14 · AC-P15 · AC-P16 · AC-P17 · AC-P17a · AC-P18 · AC-P19 · AC-P20 · AC-P21 · AC-P22 · AC-D1 · AC-D2 · AC-D3 · AC-D4

### WS-E · 日常模式会话开放（后端 · 8～10 人天 · M4；依赖 WS-C）

- [ ] **E01**: 错误码 26015 / 26017 三语 + `chat:invoke` 位清 `pending_note_key`
  **文件**: `common/errcode/open_api.py`、`packages/locales/src/api_errors/*.json` ×3、`open_api/domain/scopes.py`
  **依赖**: A01
  **覆盖 AC**: AC-35 · AC-50

- [ ] **E02**: V2 契约 schema（白名单式）+ 入参清洗 测试
  **文件**: `open_api/domain/schemas/workbench.py`（新：`WorkbenchChatRequest`（design E2 字段表，`extra='forbid'`，`run_mode` / `execution` 枚举）、`TurnResult`、`TurnEvent` 8 种事件）；测试 `test/open_api/test_workbench_schema.py`（契约外字段 400 指名；`type≠bisheng_tool` 400 指名；`run_mode=task` → 26017；`execution=async` → 26015；两者同传两码都可分辨）
  **依赖**: E01
  **覆盖 AC**: AC-34 · AC-35 · AC-50 · AC-E1

- [ ] **E03**: 抽 `WorkstationChatService.run_daily_turn` 内部事件流 + 工作台 SSE 适配器（工作台零行为变化）
  **文件**: `workstation/domain/services/chat_service.py`（`stream_chat_completion` 的日常模式分支拆为 `run_daily_turn(login_user, DailyTurnInput) -> AsyncIterator[TurnEvent]` + `render_workstation_sse(events)`；`task_mode` 分支不动；`clientTimestamp` 改可选）；测试 `test/workstation/test_daily_turn_events.py` + 工作台 SSE 回归（录制现有一轮输出逐字节对比）
  **逻辑**: design E3；**不复制链路**；V2 端点只能 import `workstation.domain.*`（RULE-5）。
  **依赖**: E02
  **覆盖 AC**: AC-36（内容一致的前提）· AC-E2

- [ ] **E04**: V2 三端点 + V2 SSE 适配器 + 归属校验
  **文件**: `open_endpoints/api/endpoints/workbench.py`（新：`POST /workbench/chat`（`chat:invoke`, S/D, `session=True`, `idempotent=True`）、`GET /workbench/turns/{turn_id}`、`POST /workbench/files`）、`open_api/domain/services/workbench_adapter.py`（新：入参映射——模型按名解析 + 同名歧义 400、知识库 / 平台工具 / 附件 / instructions 映射、模式 S 个人知识库 400；`render_v2_sse` / 非流式聚合；`turn_id` 不透明 id 生成与留存）、`open_api/domain/scopes.py`（三端点映射）；测试 `test/open_api/test_workbench_api.py`（首轮 / 续接 / 挂库 / 开工具 / 带附件 / 流式与非流式一致 / 失败轮不留存 / `turn_id` 不可枚举 / 归属不匹配 404 形状一致 / 模式 D 会话在目标工作台可见）
  **依赖**: E03 · C05 · C06
  **覆盖 AC**: AC-32 · AC-34 · AC-36 · AC-E2 · AC-E3 · AC-E4

- [ ] **E05**: 对外文档：逐项入参 / 返回 / 事件 / 拒绝清单 / 未开放能力报错形态 + 可运行示例
  **文件**: `docs/api/workbench-chat.md`（新）
  **依赖**: E04
  **覆盖 AC**: PRD §4.6.3 三.8 · vibe-058 AC-04

- [ ] **E06**: WS-E 集成 + E2E + 114 手动验证 M4 会话段
  **依赖**: E01–E05
  **覆盖 AC**: AC-32 · AC-34 · AC-35 · AC-36 · AC-50 · AC-E1 · AC-E2 · AC-E3 · AC-E4

### WS-F · P2 运营能力（后端 · 6～8 人天 · M4）

- [ ] **F01a**: 错误码 26008 / 26009 / 26011 三语 + Alembic 三列 + 模型 + Settings（基础设施）
  **文件**: `common/errcode/open_api.py`、`packages/locales/src/api_errors/*.json` ×3（跑生成脚本）、`core/database/alembic/versions/v3_0_0b1_f053_credential_p2_columns.py`（新）、`open_api/domain/models/api_credential.py`（`ip_allowlist JsonType` / `rate_limit_rpm INT` / `quota_daily_calls INT`，皆 NULL）、`core/config/open_platform.py`（`trusted_proxies: list[str] = []`）
  **回滚**: `downgrade()` 删三列（配置丢失 = 回到不限，安全方向）
  **依赖**: A02
  **覆盖 AC**: AC-24（存储前提）

- [ ] **F01b**: 缓存载荷含三列 + 签发 / 编辑端点透传 + CIDR 校验 测试与实现
  **文件**: 测试 `test/open_api/test_credential_p2_fields.py`（编辑后 3s 内新值生效；非法 CIDR 400）；`open_api/domain/services/credential_validator.py`（载荷增三列、编辑主动失效已有）、`api/endpoints/service_account_keys.py`（`KeyIssueRequest` / `KeyUpdateRequest` 增三字段，`ipaddress.ip_network` 校验）
  **依赖**: F01a
  **覆盖 AC**: AC-F4（配置面）· AC-21（编辑即时生效延伸）

- [ ] **F02**: 限流令牌桶 Lua + 日配额 + 槽位接入 测试与实现
  **文件**: `open_api/domain/services/rate_limit_service.py`（新：`acquire(credential_id, rpm)` Lua；`consume_quota(credential_id, daily)`；Redis 异常 → `26030`）、`api/dependencies.py`（③′ 限流、⑧ 配额；响应头三件）；测试 `test/open_api/test_rate_limit.py`（rpm=60 第 61 起 429；403 请求计入限流不计配额；401 两者不计；Redis 断 → 503；多进程并发原子）
  **依赖**: F01b
  **覆盖 AC**: AC-24 · AC-F1 · AC-F2

- [ ] **F03**: IP 白名单 测试与实现
  **文件**: `open_api/domain/services/client_ip.py`（新：可信代理 + `X-Forwarded-For` 取值）、`api/dependencies.py`（槽位 ⑤）；测试 `test/open_api/test_ip_allowlist.py`（直连 / 经可信代理 / 伪造 XFF 不可信 / IPv6）
  **依赖**: F01b
  **覆盖 AC**: AC-F4

- [ ] **F04**: 幂等键 测试与实现
  **文件**: `open_api/domain/services/idempotency_service.py`（新）、`open_api/api/idempotency.py`（新：`Depends(idempotency_guard)`；`IdempotentReplay` 异常 → handler 返回快照 + 头）、`api/exception_handlers.py`（注册）、三个 `idempotent=True` 端点挂依赖（`workflow/invoke`、`filelib/add_qa`、`workbench/chat` 非流式）；测试 `test/open_api/test_idempotency.py`（同键同体只执行一次 + 头；在途 409；异体 409；`stream=true` 忽略并声明；Redis 断 → 503；24h 过期）
  **依赖**: F01a · E04（第三个端点）
  **覆盖 AC**: AC-25 · AC-F2 · AC-F3

- [ ] **F05**: 发布说明 P2 段 + 对外文档（限流头 / 幂等键 / IP 白名单）+ 114 手动验证 M4 P2 段
  **依赖**: F02–F04 · A20
  **覆盖 AC**: AC-24 · AC-25 · AC-F1 · AC-F2 · AC-F3 · AC-F4

### WS-G · share-token 通道（全栈 · 5～6 人天 · M2 必需）≡ vibe Wave 4

- [ ] **G01**: Alembic `share_link.share_scope` + 模型 ≡ vibe T047
  **差异**: revision 命名 `v3_0_0b1_f053_share_link_scope.py`；`downgrade()` 删列（`app` 级分享行退化为 `session` 语义读法，回滚前须先撤销全部 `app` 级分享）。
  **依赖**: A02
  **覆盖 AC**: AC-G2（前提）

- [ ] **G02**: `ShareLinkService` 增量（撤销 / 相对秒有效期强制 / `app` 级生成）+ 测试 ≡ vibe T048 / T049
  **差异**: 无。
  **依赖**: G01
  **覆盖 AC**: AC-G2

- [ ] **G03**: 匿名作用域端点 + `/app-shares` 管理端点 ≡ vibe T050
  **差异**: 无（登录态端点挂非豁免前缀，design 坑 14）。
  **依赖**: G02
  **覆盖 AC**: AC-G3 · AC-G5

- [ ] **G04**: WS share-token 分支 + watchdog + 建连审计 + 分区键 `share:{id}` ≡ vibe T051 / T052 / T053
  **差异**: HTTP 密钥分支的裸崩修复已在 A11；本任务只加 share-token 分支、密钥与 share-token 同传以密钥为准、watchdog 3s、`open_api.ws.connect`；会话 `external_user_id='share:{share_link_id}'`（C06 的列与 DAO 参数已就位）。
  **依赖**: G02 · A11 · C06 · C08（模式头拒绝）
  **覆盖 AC**: AC-G1 · AC-G2 · AC-G4

- [ ] **G05**: platform 免登录链接改走 share-token + 撤销入口 ≡ vibe T054
  **差异**: 无。
  **依赖**: G03
  **覆盖 AC**: AC-G3（入口侧）

- [ ] **G06**: client guest 页：share-token 读取 + WS URL + HTTP 改打作用域端点 ≡ vibe T055 / T056
  **差异**: beta1 上 `client/pages/standaloneChat/StandaloneChatPage.tsx`（guest 分支 `apiVersion='v2'`）与 `pages/appChat/useChatHelpers.ts` 为改动点，落地前重定位。
  **手动验证**: platform 生成免登录链接 → 无痕窗口打开 → 能对话；撤销 → 页面 3s 内断开；直接打 `/api/v2/flows/{id}` 无头 → 401（guest 页不再依赖它）。
  **依赖**: G03 · G04
  **覆盖 AC**: AC-G3 · AC-G1

- [ ] **G07**: WS-G 集成测试 + E2E
  **依赖**: G01–G06
  **覆盖 AC**: AC-G1 · AC-G2 · AC-G3 · AC-G4 · AC-G5

---

## 依赖图（工作流级）

```
A01–A04 (M1) ─┬─▶ A05–A21 ──────────────────────────────┐
              ├─▶ B01 ─▶ B02(需 A16) · B03/B04(需 C03) · B05a/b(需 D05b) · B06(需 F01b) · B07(需 G05)
              ├─▶ C01–C04 ─▶ C05(需 A15) · C06 · C07a→b→c · C08(需 A11) · C09 · C10 ─▶ C11 ─┤ M2 = A + C + G
              ├─▶ D01–D03 ─▶ D04 ─▶ D05a/b ─▶ D06 · D07a→b ─▶ D08 · D09(需 A12) ─▶ D10(需 C10) │ M3 = + B + D
              ├─▶ E01–E02 ─▶ E03 ─▶ E04(需 C05 · C06) ─▶ E05 ─▶ E06                       │ M4 = + E + F
              ├─▶ F01a→b ─▶ F02 · F03 · F04(需 E04) ─▶ F05                                │
              └─▶ G01 ─▶ G02 ─▶ G03 ─▶ G04(需 A11 · C06 · C08) ─▶ G05 · G06 ─▶ G07 ────────┘
```

---

## 实际偏差记录

（一行指针，论证在 design.md。）
