# Tasks: F070-points-system（首钢知库积分系统）

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)  
**版本**: v2.6.0  
**模块编码**: 182  
**基线依赖**: F002 部门树 / F004 ReBAC / knowledge·approval·qa_expert·message·telemetry；Portal 兄弟仓

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-06 用户确认（含 design.md） |
| design.md | ✅ 已评审 | 与 spec 同步确认 |
| tasks.md | ✅ 已拆解 | 含阶段性无头浏览器验收门禁（2026-08-06 增补） |
| 实现 | ✅ M5 完成 / G-M5 通过 | T000–T028、G-M1~G-M5 完成；T025 Client 入口延后；可进入发布清单复检 |

---

## 开发模式

- **后端 Test-First（务实）**：账本幂等/日 cap/豁免/G3/受益人解析必须先测后实现；挂钩点可用 mock Facade。
- **阶段性验收（强制）**：每个里程碑结束后必须跑通对应 **Gate（G-Mx）**，以 **Playwright 无头浏览器** + API 断言做高标准验收；**Gate 未绿不得进入下一阶段**。
- **UI 验收默认自动化**：Portal / Platform 关键路径用 headless Chromium；仅无障碍场景（如企微扫码）可降级并记入「实际偏差记录」。
- **双库**：Alembic 用 `dialect_helpers`；revision 建议 **`f078_points_system`**（`f077` 已被 folder sort weight 占用）。
- **开关**：`points.enabled` 默认 false，挂钩打开后再计自动分。
- **自包含任务**：文件路径 + 逻辑 + AC；实现时以 design 字段名为准。
- **不做**：`point_message_template` 表；延迟入账（design §7 二期）；外链 share-links 计分。

---

## 阶段性验收门禁（Gate）

### 原则

| 项 | 要求 |
|---|---|
| 工具 | Playwright（headless Chromium）；实现期 Agent 亦可用 Cursor `user-playwright` MCP 复跑同一脚本 |
| 环境 | **基础中间件走线上测试机 `192.168.106.171`**（与 `config.yaml` 一致）；应用本机：Backend `:7860`、Portal BFF `:8010`、Portal `:5173`、Platform `:3001`（按需）、Client `:4001` |
| 账号 | 默认 `E2E_POINTS_ADMIN=admin` / `E2E_POINTS_USER=gzx01`；密码仅经 `E2E_POINTS_PASSWORD` 注入，禁止写死进 spec |
| 产物 | 每次 Gate：控制台日志 + **失败必留截图/trace**（`test-results/points-gate-mX/`）；通过则记录 commit SHA |
| 标准 | 用例映射 AC；关键文案/数值/权限断言明确；禁止「页面能开就算过」 |
| 阻塞 | **G-Mx FAIL → 禁止合并该阶段、禁止开下一阶段任务** |

### 门禁一览

| Gate | 触发时机 | 覆盖重点 | 依赖阶段任务 |
|------|---------|---------|-------------|
| **G-M1** | M1 API 可用后 | 超管登录 Portal 管理端：规则列表/调分/概览；普通用户「我的积分」摘要与明细（可先 mock 数据或种子流水）；非超管调分被拒 | T001–T008, T018–T019 最小可用；T021 可先做只读页 |
| **G-M2** | 自动发放挂钩后 | 无头走：上传/发布入库加分、G7 分享加分、G3 收藏阶梯、G4 采纳；明细出现对应流水；外链分享**不加分**；超管账号不加自动分 | T009–T013 + `points.enabled=true` |
| **G-M3** | 排行/打标/月奖后 | Platform 设公司根四级标签；首页榜 TOP10 三 Tab；我的积分部门/总榜名次；手动触发月奖后明细有 M*（或管理接口触发） | T014–T017, T022, T024 |
| **G-M4** | 运营台与前台齐后 | 规则受益人配置生效；前台 R* 扣减（Portal 或 Client）；规则弹窗无 M*、申诉为线下文案；审计列表 | T021–T025 |
| **G-M5** | 发布前 | 全链路冒烟 + 对账无 mismatch；开关关闭后面包屑/入口可降级；无严重 console error | T026–T028 |

### Gate 用例最低集（高标准）

**G-M1**

1. 超管打开 Portal 积分管理 → 见预置规则 Tab，G1 beneficiary 可选上传人/发布人。  
2. 对测试用户调分 +10 → 余额变化 → 站内信/明细可见。  
3. 普通用户打开「我的积分」→ 见余额、本月获得/扣减、明细筛选。  
4. 普通用户调调分 API/入口 → 18201 或入口不可见。

**G-M2**

1. 普通用户上传文件到部门库（非本人管理库）→ 明细出现 G2（或当前启用规则），余额增加 ≤ 日 cap。  
2. 同文件同库重复触发不双计。  
3. 库间 SHARE 审批通过 → G7 流水（规则启用时）。  
4. 创建外链 share-link → **无**新积分流水。  
5. 超管上传 → **无**自动分流水。

**G-M3**

1. 超管 Platform 指定公司根 → 子节点 org_level 四级正确。  
2. Portal 首页榜切换 本月/本年/总榜，长度 ≤10，无「我」置底行。  
3. 我的积分展示部门排名（或 —）与 `rank_refreshed_at`。

**G-M4**

1. 改 G1 beneficiary 为 publisher 后，发布路径得分落在发布人。  
2. 超管前台 R* 扣减 → 余额下降、明细 direction=deduct。  
3. 规则弹窗无管理员月奖、申诉文案含「线下」。

**G-M5**

1. 串联 G-M1~M4 冒烟全绿。  
2. `points.enabled=false` 后新上传不再加分。  
3. 对账任务无 balance mismatch。

---

## 执行阶段计划

1. **M0 脚手架**：Playwright + 联调账号约定 + Gate 脚本骨架。  
2. **M1 账本底座** → **G-M1**。  
3. **M2 自动发放** → **G-M2**。  
4. **M3 排行与月奖** → **G-M3**。  
5. **M4 运营台与前台** → **G-M4**。  
6. **M5 运维与发布** → **G-M5**。

---

## Tasks

### 阶段 0：基础设施 + 验收脚手架

- [x] **T000**: Playwright 无头验收脚手架  
  **文件**（建议）:  
  - `src/backend/test/e2e_ui/points/playwright.config.ts`（或 Portal 仓 `e2e/points/`，二选一，优先与 Portal 同仓若页面测为主）  
  - `…/points/fixtures/auth.ts`、`…/gates/gm1.spec.ts`（先建空骨架）  
  - `…/README.md`（如何起栈、环境变量、跑 Gate）  
  **逻辑**: headless Chromium（可用本机 Chrome channel）；baseURL Portal；截图/trace on failure；默认账号 admin/gzx01；密码仅 env  
  **验收标准**: `npx playwright test --list` 能列出 Gate 套件；文档写明中间件 `192.168.106.171` 与 `E2E_POINTS_*`  
  **覆盖 AC**: —（基建）  
  **依赖**: 无；中间件指向测试机  

- [x] **T001**: 错误码 182xx  
  **文件**: `src/backend/bisheng/common/errcode/points.py`  
  **逻辑**: `PointsPermissionDeniedError`(18201)、`PointsInvalidAdjustError`(18202)、`PointsRuleConflictError`(18203)、`PointsRuleNotFoundError`(18204)、`PointsCompanyRootConflictError`(18205)、`PointsIdempotentReplayError`(18206)；继承 `BaseErrorCode`  
  **覆盖 AC**: AC-03, AC-06, AC-20, AC-21  
  **依赖**: 无

- [x] **T002**: Alembic 迁移 + ORM 模型  
  **文件**:  
  - `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f078_points_system.py`  
  - `src/backend/bisheng/points/domain/models/*.py`  
  - `src/backend/bisheng/database/models/department.py`（`org_level`）  
  **逻辑**: 按 design §1 建表：`user_point_account`、`user_point_log`（含 `beneficiary_role`）、`point_rule`、`point_copy`、`point_rank_snapshot`、`point_favorite_tier_award`、`point_sync_outbox`；`department.org_level`；种子预置 G1–G4/R1–R3/M1/M4/M6 + 5 条说明文案；**不建** message_template 表  
  **覆盖 AC**: AC-25, AC-29  
  **依赖**: 无

- [x] **T003**: Repository 实现  
  **文件**: `src/backend/bisheng/points/domain/repositories/**`  
  **逻辑**: 账户锁行 `FOR UPDATE`、流水 append-only、规则 CRUD、文案、快照替换写、pending outbox、G3 tier upsert；禁止 Service 内散落 ORM  
  **覆盖 AC**: AC-01  
  **依赖**: T002

### 阶段 1：账本与规则核心 → 门禁 G-M1

- [x] **T004**: `PointsLedgerService` 单元测试  
  **文件**: `src/backend/test/points/test_points_ledger_service.py`  
  **逻辑**: 覆盖 award/deduct/adjust：幂等、日 cap clamp、负余额、禁止 delta=0、并发同 key  
  **覆盖 AC**: AC-01, AC-02, AC-11  
  **依赖**: T003

- [x] **T005**: `PointsLedgerService` 实现  
  **文件**: `src/backend/bisheng/points/domain/services/points_ledger_service.py`  
  **逻辑**: 同事务写 log + 更新 account；自动发放必填 idempotency_key；写 sync_outbox pending；调用 Notify（best-effort）  
  **测试**: T004 全绿  
  **覆盖 AC**: AC-01, AC-02, AC-11, AC-23  
  **依赖**: T004

- [x] **T006**: 站内信常量 + `PointsNotifyService`  
  **文件**: `src/backend/bisheng/points/domain/constants/notify_templates.py`, `.../points_notify_service.py`  
  **逻辑**: 写死 earn_publish/earn_share/earn_favorite/earn_adopt/deduct_admin/adjust_admin；渲染后 `MessageService.send_message`，`action_code=points_changed`  
  **覆盖 AC**: AC-18  
  **依赖**: T005

- [x] **T007**: `PointsRuleService` 测试 + 实现  
  **文件**: `test/points/test_points_rule_service.py`, `points/domain/services/points_rule_service.py`  
  **逻辑**: 规则 CRUD/启停；beneficiary 按 rule_code 白名单校验；说明文案 PUT；非超管 18201  
  **覆盖 AC**: AC-03, AC-05, AC-06, AC-07  
  **依赖**: T003, T001

- [x] **T008**: 超管判定工具  
  **文件**: `points/domain/services/points_auth.py`（或复用现有 UserPayload 能力）  
  **逻辑**: 统一 `require_platform_admin` / `is_platform_super_admin`；自动分与榜单过滤超管  
  **覆盖 AC**: AC-03, AC-12, AC-21  
  **依赖**: 无

- [x] **T018**: 用户端 API（M1 可先交付）  
  **文件**: `points/api/endpoints/me.py`, router 注册  
  **逻辑**: `GET /me/summary`、`/me/logs`、`/rules/public`、`/leaderboard`；PageData  
  **覆盖 AC**: AC-07, AC-14, AC-15, AC-24  
  **依赖**: T005, T007

- [x] **T019**: 管理端 API（M1 可先交付）  
  **文件**: `points/api/endpoints/admin.py`  
  **逻辑**: overview、rules、copies、users、adjust、user logs、audit-logs、deduct；**无** message-templates  
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-17, AC-19  
  **依赖**: T005, T007, T008

- [x] **T021a**: Portal — 我的积分 + 管理端最小页（支撑 G-M1）  
  **仓**: Portal  
  **逻辑**: 账号菜单入口、摘要/明细、管理端规则列表与调分表单（可后续美化）  
  **覆盖 AC**: AC-02, AC-07, AC-14  
  **依赖**: T018, T019, T000

- [x] **G-M1**: 无头浏览器验收 — 账本与管理可读可调  
  **文件**: `e2e/.../gates/gm1.spec.ts`  
  **逻辑**: 执行「Gate 用例最低集 · G-M1」；失败留 screenshot/trace  
  **通过标准**: 全部用例 green；无未捕获 pageerror  
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-07, AC-14  
  **依赖**: T000, T018, T019, T021a  
  **阻塞**: 未通过不得开始 T009

### 阶段 2：自动发放 Facade 与挂钩 → 门禁 G-M2

- [x] **T009**: `PointsAwardFacade` 测试 ✅ 2026-08-06  
  **文件**: `test/points/test_points_award_facade.py`  
  **逻辑**: 个人库/收藏库 skip；creator/admin 豁免；超管 skip；beneficiary 解析；规则 disabled/cap；异常不向外抛  
  **覆盖 AC**: AC-08, AC-11, AC-12, AC-28  
  **依赖**: T005, T007, **G-M1**；豁免按 **P7=B 受益人**（见 design §0.1）

- [x] **T010**: `PointsAwardFacade` 实现 ✅ 2026-08-06  
  **文件**: `points/domain/services/points_award_facade.py`  
  **逻辑**: `on_space_file_ready` / `on_document_shared` / `on_favorite_changed` / `on_answer_adopted`；受 `points.enabled` 控制  
  **测试**: T009 全绿（19 passed）  
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-30, AC-26  
  **依赖**: T009

- [x] **T011**: 挂钩 — 上传 / 发布入库（G1/G2/G5/G6） ✅ 2026-08-06  
  **文件**: `KnowledgeSpaceService.add_file`；`shougang_approval_handler` 发布 F059/旧版复制  
  **逻辑**: `notify_space_files_ready` → `on_space_file_ready`；独立会话；不影响主业务  
  **覆盖 AC**: AC-08, AC-26, AC-28  
  **依赖**: T010

- [x] **T012**: 挂钩 — G3 收藏阶梯 ✅ 2026-08-06  
  **文件**: `create_shougang_portal_favorite`（新收藏路径）+ `point_favorite_tier_award`  
  **逻辑**: 去重人数；补差价；终身 ≤15；已存在收藏 early-return 不触发  
  **覆盖 AC**: AC-09  
  **依赖**: T010

- [x] **T013**: 挂钩 — G4 采纳 + G7 库间 SHARE ✅ 2026-08-06  
  **文件**: `QuestionService.adopt_answer`；Share handler `share_approved` 之后  
  **逻辑**: G4/G7 幂等键；禁止 share-links（未挂外链）  
  **覆盖 AC**: AC-10, AC-30, AC-26  
  **依赖**: T010

- [x] **T020**: 功能开关配置 ✅ 2026-08-06  
  **文件**: `core/config/settings.py` → `PointsConf`；Facade 读取 `settings.points.enabled`  
  **逻辑**: `points.enabled` 等；默认 false；单测可注入覆盖  
  **依赖**: T010

- [x] **G-M2**: 无头浏览器验收 — 自动发放主路径 ✅ 2026-08-06  
  **文件**: `e2e_ui/points/gates/gm2.spec.ts` + `helpers/gm2_trigger.py`  
  **逻辑**: API/Facade 造数 + Portal「我的积分」明细断言；外链负例；超管负例  
  **通过标准**: **4/4 green**（`E2E_POINTS_RUN_GATES=1 npm run test:gm2`）  
  **覆盖 AC**: AC-08, AC-12, AC-26, AC-30（G3/G4 UI 路径留 M4/后续）  
  **依赖**: T011–T013, T020, T021a  
  **阻塞**: 未通过不得开始 T014

### 阶段 3：排行、月奖、组织打标 → 门禁 G-M3

- [x] **T014**: `DepartmentOrgLevelService` 测试 + 实现 + API ✅ 2026-08-07  
  **文件**: `points/.../department_org_level_service.py`；`department/api/.../department_org_level.py`  
  **逻辑**: 唯一 company；级联 dept/office/squad；`GET /org-levels` + `POST /{id}/set-company-root`  
  **覆盖 AC**: AC-20, AC-21（AC-22 属排行展示，随 T015）  
  **依赖**: T002, T008, **G-M2**

- [x] **T015**: `PointsRankService` + 小时 Beat ✅ 2026-08-07  
  **文件**: `points/.../points_rank_service.py`；`worker/points/tasks.py`；Beat `points_refresh_rank_snapshots`  
  **逻辑**: month/year/all 快照；部门桶；过滤超管；`my_summary.dept_rank` 读快照  
  **覆盖 AC**: AC-15, AC-16, AC-22  
  **依赖**: T003, T014

- [x] **T016**: 月奖 Beat ✅ 2026-08-07  
  **文件**: `points/.../points_monthly_reward_service.py`；`worker/points/tasks.py`；Beat `points_monthly_admin_rewards`  
  **逻辑**: 每月 1 日 00:05 结算上月；上月登录≥1（日活 ES）；多角色取最高 M*；幂等 `reward:{rule}:{user}:{yyyy-mm}`  
  **覆盖 AC**: AC-13  
  **依赖**: T005, T007, T008

- [x] **T017**: 对账 + sync outbox drain ✅ 2026-08-07  
  **文件**: `points_reconcile_service.py` / `points_sync_outbox_service.py`；Beat `points_reconcile_balances` / `points_drain_sync_outbox`  
  **逻辑**: 日对账只告警不改流水；outbox 关闭时保持 pending，开启且无适配器则 skipped  
  **覆盖 AC**: AC-04, AC-23  
  **依赖**: T005

- [x] **T022**: Portal — 首页积分榜 ✅ 2026-08-07  
  **文件**: Portal `PointsLeaderboardPanel.tsx` + `fetchPointsLeaderboard`；BiSheng leaderboard 补 user_name/dept_name  
  **逻辑**: 本月/本年/总榜 TOP10；无「我」置底；空态文案；数据来自小时快照  
  **覆盖 AC**: AC-15  
  **依赖**: T018, T015

- [x] **T024**: Platform — 组织四级打标 UI ✅ 2026-08-07  
  **文件**: `DepartmentPage` 树徽章 + `DepartmentSettings`「设为公司根」；API `org-levels` / `set-company-root`  
  **逻辑**: 仅平台超管可见打标按钮；树/详情展示 org_level；非超管后端仍 18201  
  **覆盖 AC**: AC-20, AC-21  
  **依赖**: T014

- [x] **G-M3**: 无头浏览器验收 — 榜单与组织标签 ✅ 2026-08-07  
  **文件**: `e2e_ui/points/gates/gm3.spec.ts` + `helpers/gm3_trigger.py`  
  **逻辑**: Platform「设为公司根」入口可见；Portal 三 Tab 榜无「我」置底；我的积分部门/总榜；org_level 只读级联校验；破坏性打标需 `E2E_POINTS_ALLOW_ORG_MUTATE=1`  
  **通过标准**: **4/4 green**（1 skipped mutate）；`E2E_POINTS_RUN_GATES=1 npm run test:gm3`  
  **覆盖 AC**: AC-15, AC-16, AC-20, AC-22  
  **依赖**: T015, T022, T024  
  **阻塞**: 未通过不得开始 T023 完整运营台验收

### 阶段 4：运营台与前台齐套 → 门禁 G-M4

- [x] **T021b**: Portal — 我的积分完善（规则弹窗/空态/999+） ✅ 2026-08-07  
  **文件**: Portal `PointsPage.tsx`（`rank_refreshed_at`、999+、空态、规则弹窗过滤 M*）  
  **逻辑**: 展示排名刷新时间；总榜 `999+` 不误拼 `#`；明细空态引导文案；规则弹窗仅 earn/deduct + 线下申诉 copies  
  **覆盖 AC**: AC-07, AC-14, AC-27  
  **依赖**: T021a, **G-M3**

- [x] **T023**: Portal — 积分管理后台完整 ✅ 2026-08-07  
  **文件**: Portal `PointsManagementPanel` + `PointsRuleEditModal`；BiSheng `admin/users` / `admin/audit-logs`  
  **逻辑**: 概览三绝对数；规则四 Tab（获取/扣减/月奖/文案）可编辑分值·日 cap·受益人·启停；用户列表+操作记录；列表内「调整积分」直接调分（正加负减，不强制 R*）  
  **覆盖 AC**: AC-02, AC-05, AC-06, AC-19（AC-17 前台违规扣减可延后 T025）  
  **依赖**: T019

- [x] **T025**: Client（可选）— 前台 R* 扣减 — **延后** ✅ 2026-08-07  
  **覆盖 AC**: AC-17（浏览器路径由 Portal 管理端「违规扣减」承担）  
  **依赖**: T019  
  **备注**: Client 文档/问答页入口未做；G-M4 用 Portal `PointsDeductModal` + `POST /admin/deduct` 作为扣减路径

- [x] **G-M4**: 无头浏览器验收 — 运营配置与扣减 ✅ 2026-08-07  
  **文件**: `e2e_ui/points/gates/gm4.spec.ts` + `helpers/gm4_trigger.py`  
  **逻辑**: G1 beneficiary→publisher 后发分落发布人；Portal「违规扣减」R1；规则弹窗无月奖文案且含「线下」；审计可见  
  **通过标准**: **3/3 green**（`E2E_POINTS_RUN_GATES=1 npm run test:gm4`）  
  **覆盖 AC**: AC-06, AC-07, AC-17, AC-19, AC-27  
  **依赖**: T021b, T023  
  **阻塞**: 未通过不得宣称功能可交付

### 阶段 5：发布前 → 门禁 G-M5

- [x] **T026**: 本地联调（dev-stack）+ 补齐 Gate 数据工厂 ✅ 2026-08-07  
  **文件**: `e2e_ui/points/helpers/factory_trigger.py` + `factory.ts`  
  **逻辑**: 统一造数 G2/G3/G4/G7、超管负例、外链负例、对账、`enabled=false`、schema 检查  
  **覆盖 AC**: AC-08~AC-16, AC-26, AC-30  
  **依赖**: T011–T025

- [x] **T027**: 双库迁移冒烟 ✅ 2026-08-07  
  **文件**: `test/points/test_points_dual_db_smoke.py`  
  **逻辑**: 静态校验 dialect_helpers；MySQL 表可读（或 skip）；DM8 macOS skip / CI Linux  
  **覆盖 AC**: AC-25  
  **依赖**: T002

- [x] **T028**: 上线检查清单记录 ✅ 2026-08-07  
  **文件**: `features/v2.6.0/070-points-system/release-checklist.md`  
  **逻辑**: design §4.5；灰度开关；对账；发布顺序；Gate 记录  
  **覆盖 AC**: AC-04, AC-23, AC-29  
  **依赖**: T026, T027

- [x] **G-M5**: 无头浏览器验收 — 发布前全量冒烟 ✅ 2026-08-07  
  **文件**: `e2e_ui/points/gates/gm5.spec.ts`；`npm run test:gm5` 串行 gm1–gm4 + gm5  
  **逻辑**: 对账无 mismatch；`enabled=false` 不加分；outbox 安全；入口冒烟；回归 gm1–gm4  
  **通过标准**: **22 passed / 1 skipped**（org mutate）  
  **覆盖 AC**: 回归 AC-01~AC-30 主路径  
  **依赖**: G-M1…G-M4, T027, T028  
  **阻塞**: 未通过不得合入主干/发版

---

## Agent 执行约定（实现期）

1. 完成某阶段最后开发任务后，**必须**启动联调栈并跑对应 `G-Mx`（headless）。  
2. 可用 `npx playwright test …/gmX.spec.ts` 或 Cursor Playwright MCP 按同一用例操作；结果以脚本可重复执行为准。  
3. Gate 失败：修缺陷 → 重跑 Gate → 通过后再勾选任务并进入下一阶段。  
4. 在 `tasks.md` 状态表或下方偏差记录写明：Gate 通过时间、commit、报告路径。

---

## AC 覆盖矩阵（摘要）

| AC | 主要任务 / Gate |
|----|----------------|
| AC-01~04 | T004–T005, T017, G-M5 |
| AC-05~07 | T007, T018, T021*, T023, G-M1, G-M4 |
| AC-08~13, AC-30, AC-26 | T009–T013, T016, G-M2 |
| AC-14~16, AC-22 | T015, T018, T021–T022, G-M3 |
| AC-17~19 | T006, T019, T023, T025, G-M4 |
| AC-20~21 | T014, T024, G-M3 |
| AC-23~25, AC-27~29 | T002, T005, T017, T021b, T027–T028, G-M5 |

---

## 实际偏差记录

> 实现阶段填写。

- 2026-08-06：源码曾被清空，按简化 DDD（单 `points_repository`）恢复；API 已接真实查询/调分/规则启停。
- 2026-08-06：**G-M1 PASS**（`E2E_POINTS_RUN_GATES=1 npm run test:gm1`，**4/4**：规则列表、调分、我的积分、非超管 18201）；Playwright 使用本机 Chrome `channel: 'chrome'`；登录改走 `/login`。
- 调分曾因 MySQL 严格模式未写入 `occurred_at` 失败，已在 `PointsLedgerService` 显式落业务时间。
- Portal 调分默认备注改为 ≥5 字以匹配后端校验。
- 2026-08-06：`design.md` §0.1 写入 P1–P7；**P7 用户确认 = B（按受益人豁免）**，T009 可开。
- 2026-08-06：从 `积分PRD V1.1.docx` 抽出 15 张模块原型 → `ui-prototypes/`（Portal 仓 `docs/points-ui-prototypes/` 有副本）；前端以该目录为准。
- 2026-08-06：**T009/T010/T020 完成**：`PointsAwardFacade` + 单测；空间等级映射 `public→G1 / department→G2 / team→G5 / team_ks→G6`；P7=B；`points.enabled` 默认 false。
- 2026-08-06：**T011–T013 完成**：`points_award_hooks.py` 独立会话旁路；挂 `add_file` / 发布审批 / 收藏 / 采纳 / `share_approved`。种子补 G5/G6/G7（仅空租户首次 seed；已有库需管理端补规则或手工 INSERT）。`test/points/` 22 passed。
- 2026-08-06：**G-M2 PASS 4/4**。修复 Facade 读开关路径（`config_service.settings`，原先误 import 导致始终 disabled）。本地 `config.yaml` `points.enabled=true`；171 库补 G7（id=11）。Gate 用 hooks 造数 + UI 断言（完整上传/审批 UI 流未在门禁内重放）。
- 2026-08-07：**T014 完成**：`DepartmentOrgLevelService` + API；单测 5 条；联调冒烟 `gzx01` 调 `set-company-root` → **18201**，`GET org-levels` 200（46 节点）。未在共享库执行真实打标（避免误改 org_level）。`points_auth` 同时认 `is_global_super`。
- 2026-08-07：**T023/T021b 完成**；用户列表直接调分弹窗对齐设计（+/- 按钮 + 纯数字）；调分校验错误改为弹窗内展示。
- 2026-08-07：**T025 延后**（Client 文档页 R* 入口）；Portal 管理端补「违规扣减」弹窗作 AC-17 浏览器路径。**G-M4 PASS 3/3**。
- 2026-08-07：**T026–T028 + G-M5 PASS**（`npm run test:gm5` → 22 passed / 1 skipped）。统一 `factory_trigger`；双库静态冒烟；`release-checklist.md`；修 gm3「排名」strict 选择器。
