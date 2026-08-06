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
| tasks.md | ✅ 已拆解 | 本文件；实现前可再跑 `/sdd-review … tasks` |
| 实现 | 🔲 未开始 | 0 / 28 完成 |

---

## 开发模式

- **后端 Test-First（务实）**：账本幂等/日 cap/豁免/G3/受益人解析必须先测后实现；挂钩点可用 mock Facade。
- **前端手动验证**：Portal / Platform；Client 扣减入口可选。
- **双库**：Alembic 用 `dialect_helpers` + `table_exists`/`index_exists`；revision 建议 `f077_points_system`（避开已有 f070）。
- **开关**：`points.enabled` 默认 false，挂钩打开后再计自动分。
- **自包含任务**：文件路径 + 逻辑 + AC；实现时以 design 字段名为准。
- **不做**：`point_message_template` 表；延迟入账（design §7 二期）；外链 share-links 计分。

---

## 执行阶段计划

1. **M1 账本底座**：迁移、账户/流水、规则种子、手动调分、站内信常量、用户读 API。  
2. **M2 自动发放**：AwardFacade + 上传/发布/G3/G4/G7 挂钩。  
3. **M3 排行与月奖**：org_level 打标、小时榜、月奖 Beat。  
4. **M4 运营台与前台**：Portal 我的积分/榜/管理；Platform 打标；可选 Client 扣减。  
5. **M5 运维**：对账、sync outbox、开关灰度。

---

## Tasks

### 阶段 0：基础设施

- [ ] **T001**: 错误码 182xx  
  **文件**: `src/backend/bisheng/common/errcode/points.py`  
  **逻辑**: `PointsPermissionDeniedError`(18201)、`PointsInvalidAdjustError`(18202)、`PointsRuleConflictError`(18203)、`PointsRuleNotFoundError`(18204)、`PointsCompanyRootConflictError`(18205)、`PointsIdempotentReplayError`(18206)；继承 `BaseErrorCode`  
  **覆盖 AC**: AC-03, AC-06, AC-20, AC-21  
  **依赖**: 无

- [ ] **T002**: Alembic 迁移 + ORM 模型  
  **文件**:  
  - `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f077_points_system.py`  
  - `src/backend/bisheng/points/domain/models/*.py`  
  - `src/backend/bisheng/database/models/department.py`（`org_level`）  
  **逻辑**: 按 design §1 建表：`user_point_account`、`user_point_log`（含 `beneficiary_role`）、`point_rule`、`point_copy`、`point_rank_snapshot`、`point_favorite_tier_award`、`point_sync_outbox`；`department.org_level`；种子预置 G1–G4/R1–R3/M1/M4/M6 + 5 条说明文案；**不建** message_template 表  
  **覆盖 AC**: AC-25, AC-29  
  **依赖**: 无

- [ ] **T003**: Repository 实现  
  **文件**: `src/backend/bisheng/points/domain/repositories/**`  
  **逻辑**: 账户锁行 `FOR UPDATE`、流水 append-only、规则 CRUD、文案、快照替换写、pending outbox、G3 tier upsert；禁止 Service 内散落 ORM  
  **覆盖 AC**: AC-01  
  **依赖**: T002

### 阶段 1：账本与规则核心

- [ ] **T004**: `PointsLedgerService` 单元测试  
  **文件**: `src/backend/test/points/test_points_ledger_service.py`  
  **逻辑**: 覆盖 award/deduct/adjust：幂等、日 cap clamp、负余额、禁止 delta=0、并发同 key  
  **覆盖 AC**: AC-01, AC-02, AC-11  
  **依赖**: T003

- [ ] **T005**: `PointsLedgerService` 实现  
  **文件**: `src/backend/bisheng/points/domain/services/points_ledger_service.py`  
  **逻辑**: 同事务写 log + 更新 account；自动发放必填 idempotency_key；写 sync_outbox pending；调用 Notify（best-effort）  
  **测试**: T004 全绿  
  **覆盖 AC**: AC-01, AC-02, AC-11, AC-23  
  **依赖**: T004

- [ ] **T006**: 站内信常量 + `PointsNotifyService`  
  **文件**: `src/backend/bisheng/points/domain/constants/notify_templates.py`, `.../points_notify_service.py`  
  **逻辑**: 写死 earn_publish/earn_share/earn_favorite/earn_adopt/deduct_admin/adjust_admin；渲染后 `MessageService.send_message`，`action_code=points_changed`  
  **覆盖 AC**: AC-18  
  **依赖**: T005

- [ ] **T007**: `PointsRuleService` 测试 + 实现  
  **文件**: `test/points/test_points_rule_service.py`, `points/domain/services/points_rule_service.py`  
  **逻辑**: 规则 CRUD/启停；beneficiary 按 rule_code 白名单校验（G1/2/5/6: uploader|publisher；G7: uploader|sharer；G3/G4/M 锁定）；说明文案 PUT；非超管 18201  
  **覆盖 AC**: AC-03, AC-05, AC-06, AC-07  
  **依赖**: T003, T001

- [ ] **T008**: 超管判定工具  
  **文件**: `points/domain/services/points_auth.py`（或复用现有 UserPayload 能力）  
  **逻辑**: 统一 `require_platform_admin` / `is_platform_super_admin`；自动分与榜单过滤超管  
  **覆盖 AC**: AC-03, AC-12, AC-21  
  **依赖**: 无

### 阶段 2：自动发放 Facade 与挂钩

- [ ] **T009**: `PointsAwardFacade` 测试  
  **文件**: `test/points/test_points_award_facade.py`  
  **逻辑**: 个人库/收藏库 skip；creator/admin 豁免；超管 skip；beneficiary 解析；规则 disabled/cap；异常不向外抛  
  **覆盖 AC**: AC-08, AC-11, AC-12, AC-28  
  **依赖**: T005, T007

- [ ] **T010**: `PointsAwardFacade` 实现  
  **文件**: `points/domain/services/points_award_facade.py`  
  **逻辑**: `on_space_file_ready` / `on_document_shared` / `on_favorite_changed` / `on_answer_adopted`；受 `points.enabled` 总开关控制  
  **测试**: T009 全绿  
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-30, AC-26  
  **依赖**: T009

- [ ] **T011**: 挂钩 — 上传 / 发布入库（G1/G2/G5/G6）  
  **文件**: knowledge 上传成功路径；`approval/.../shougang_approval_handler` 发布成功路径  
  **逻辑**: 成功后调用 `on_space_file_ready`；幂等 `earn:{rule}:{file_id}:{space_id}`；try/except 不影响主业务  
  **覆盖 AC**: AC-08, AC-26, AC-28  
  **依赖**: T010  
  **测试降级**: 可补集成测或联调清单

- [ ] **T012**: 挂钩 — G3 收藏阶梯  
  **文件**: favorite 成功路径 + `point_favorite_tier_award`  
  **逻辑**: 去重收藏人数；补差价；终身 ≤15；取消再达不重发  
  **覆盖 AC**: AC-09  
  **依赖**: T010

- [ ] **T013**: 挂钩 — G4 采纳 + G7 库间 SHARE  
  **文件**: `qa_expert` adopt；`share_approved` 成功之后  
  **逻辑**: G4 `earn:G4:{answer_id}`；G7 `earn:G7:{share_entry_id}`；**禁止**挂 share-links  
  **覆盖 AC**: AC-10, AC-30, AC-26  
  **依赖**: T010

### 阶段 3：排行、月奖、组织打标

- [ ] **T014**: `DepartmentOrgLevelService` 测试 + 实现 + API  
  **文件**: `points/.../department_org_level_service.py`（或 department 模块扩展）、Platform 可调 API  
  **逻辑**: 唯一 company；级联 dept/office/squad；相对深度≥3 仍为 squad；非超管 18201  
  **覆盖 AC**: AC-20, AC-21, AC-22  
  **依赖**: T002, T008

- [ ] **T015**: `PointsRankService` + 小时 Beat  
  **文件**: `points/.../points_rank_service.py`, `worker/points/tasks.py`, `CeleryTaskSettings`  
  **逻辑**: 刷新 month/year/all 快照；部门桶=主部门向上最近 dept；过滤超管；TOP10 读快照  
  **覆盖 AC**: AC-15, AC-16, AC-22  
  **依赖**: T003, T014

- [ ] **T016**: 月奖 Beat  
  **文件**: `points/.../points_monthly_reward_service.py`, worker  
  **逻辑**: 每月 1 日 00:05 Asia/Shanghai；登录≥1；多角色取最高 M*；幂等 `reward:{rule}:{user_id}:{yyyy-mm}`  
  **覆盖 AC**: AC-13  
  **依赖**: T005, T007, T008

- [ ] **T017**: 对账 + sync outbox drain  
  **文件**: worker tasks  
  **逻辑**: 日对账 balance vs sum(delta) 告警；drain 在无外部配置时 skip/pending 不失败  
  **覆盖 AC**: AC-04, AC-23  
  **依赖**: T005

### 阶段 4：HTTP API

- [ ] **T018**: 用户端 API  
  **文件**: `points/api/endpoints/me.py`（或等价）, router 注册  
  **逻辑**: `GET /me/summary`、`/me/logs`、`/rules/public`、`/leaderboard`；PageData 分页  
  **覆盖 AC**: AC-07, AC-14, AC-15, AC-24  
  **依赖**: T005, T007, T015

- [ ] **T019**: 管理端 API  
  **文件**: `points/api/endpoints/admin.py`  
  **逻辑**: overview、rules、copies、users、adjust、user logs、audit-logs、deduct；超管校验；**无** message-templates  
  **覆盖 AC**: AC-02, AC-03, AC-05, AC-06, AC-17, AC-19  
  **依赖**: T005, T007, T008

- [ ] **T020**: 功能开关配置  
  **文件**: settings / DB config 读取  
  **逻辑**: `points.enabled` / `notify_enabled` / `sync_outbox_enabled` / rank&monthly flags；默认 enabled=false  
  **覆盖 AC**: —（发布策略）  
  **依赖**: T010

### 阶段 5：前端（手动验证）

- [ ] **T021**: Portal — 我的积分  
  **仓**: `shougang-group-knowledge-portal`  
  **文件**: Header 入口、积分页（统计+明细+规则弹窗）  
  **逻辑**: 调用户端 API；空态；999+；不展示 M*  
  **覆盖 AC**: AC-07, AC-14, AC-27  
  **手动验证**: 登录 Portal → 账号菜单「我的积分」→ 核对余额/明细/规则弹窗  
  **依赖**: T018；BFF 代理 `/api/v1/points/**` 如需要

- [ ] **T022**: Portal — 首页积分榜  
  **文件**: `HomePage.tsx` 去掉 mock，接 leaderboard API；无「我」置底行  
  **覆盖 AC**: AC-15  
  **手动验证**: 切换本月/本年/总榜 TOP10  
  **依赖**: T018, T015

- [ ] **T023**: Portal — 积分管理后台  
  **文件**: `AdminPage` 菜单：概览/规则/用户调分/审计/说明文案  
  **覆盖 AC**: AC-02, AC-05, AC-06, AC-17, AC-19  
  **手动验证**: 改规则受益人、调分、扣减、概览三绝对数  
  **依赖**: T019

- [ ] **T024**: Platform — 组织四级打标  
  **文件**: Platform 部门树「设为公司根」  
  **覆盖 AC**: AC-20, AC-21  
  **手动验证**: 超管打标后四级正确；非超管无按钮/接口 18201  
  **依赖**: T014

- [ ] **T025**: Client（可选）— 前台 R* 扣减入口  
  **文件**: 文档列表/阅读、问答删除弹窗  
  **逻辑**: 仅平台管理员可见；调 `admin/deduct`  
  **覆盖 AC**: AC-17  
  **依赖**: T019  
  **备注**: 若排期紧可延后，不影响 Portal 主闭环

### 阶段 6：联调与验收

- [ ] **T026**: 本地联调清单（dev-stack）  
  **逻辑**: 开 `points.enabled`；走上传/发布/分享/收藏/采纳/调分/榜/月奖（可手动触发 task）；确认外链不计分  
  **覆盖 AC**: AC-08~AC-16, AC-26, AC-30  
  **依赖**: T011–T025

- [ ] **T027**: 双库迁移冒烟  
  **逻辑**: MySQL 本地 + CI/DM8 迁移升级；抽查读写  
  **覆盖 AC**: AC-25  
  **依赖**: T002

- [ ] **T028**: 上线检查清单执行记录  
  **逻辑**: 按 design §4.5 勾选；灰度开关；对账首次跑通  
  **覆盖 AC**: AC-04, AC-23, AC-29  
  **依赖**: T026, T027

---

## AC 覆盖矩阵（摘要）

| AC | 主要任务 |
|----|---------|
| AC-01~04 | T004–T005, T017 |
| AC-05~07 | T007, T018, T021, T023 |
| AC-08~13, AC-30, AC-26 | T009–T013, T016 |
| AC-14~16, AC-22 | T015, T018, T021–T022 |
| AC-17~19 | T006, T019, T023, T025 |
| AC-20~21 | T014, T024 |
| AC-23~25, AC-27~29 | T002, T005, T017, T021, T027–T028 |

---

## 实际偏差记录

> 实现阶段填写。

- （暂无）
