# Feature: F070-points-system（首钢知库积分系统）

**关联 PRD**: [../../../docs/PRD/积分系统/积分系统需求分析-V1.1.md](../../../docs/PRD/%E7%A7%AF%E5%88%86%E7%B3%BB%E7%BB%9F/%E7%A7%AF%E5%88%86%E7%B3%BB%E7%BB%9F%E9%9C%80%E6%B1%82%E5%88%86%E6%9E%90-V1.1.md) §1–§11（含产品决议）；原文 PRD V1.1 见同目录抽取稿  
**后端设计方案（DB / 接口契约 / 时序图 / 升级）**: **[design.md](./design.md)** ← 实现以该文档字段与流程为准  
**优先级**: P0（激励闭环主能力）  
**所属版本**: v2.6.0  
**模块编码**: **182**（`points`，新建 `common/errcode/points.py`）  
**依赖**: F002 部门树 + F004 ReBAC + F009 组织同步（只读）+ F012 多租户 + 现有 knowledge / approval 发布结果 / qa_expert / message / telemetry 日活；Portal 兄弟仓前端

> **范围边界（产品决议基线）**
> - **纳入**：积分账户与 append-only 流水；规则 G*/R*/M* 配置（含可增编码）；自动发放（上传/发布入库、**知识库间 SHARE 分享 G7**、收藏阶梯、问答采纳、月奖）；手动调分与前台 R* 扣减；我的积分；首页 TOP10 榜；排行快照；说明文案（`point_copy`）；站内信文案**代码常量**；组织 `org_level` 打标；外部同步 Outbox 骨架。
> - **明确排除 / 延后**：门户**外链** `share-links` 不计分；站内申诉；冻结/过期；兑换核销；管理概览环比；首页「我」置底行；历史补分；「文档被订阅」规则；协同办公真实联调（不阻塞上线）；**延迟入账反作弊（见 design.md §7，本期不做）**。
> - **端侧**：用户端与积分运营后台 → **Portal**；组织打标 → **Platform（仅超管）**；Client 仅可选挂前台 R* 扣减入口。

---

## 1. 概述与用户故事

**故事 A（贡献者）**：  
作为 **普通登录用户**，  
我希望 **因上传/发布知识、被收藏、回答被采纳等获得积分，并在「我的积分」看到余额、明细与排名**，  
以便 **贡献行为被量化激励**。

**故事 B（浏览者）**：  
作为 **Portal 首页用户**，  
我希望 **看到本月/本年/总榜 TOP10**，  
以便 **感知榜样并参与贡献**。

**故事 C（平台运营）**：  
作为 **平台超级管理员**，  
我希望 **在 Portal 配置规则/说明文案、调分与审计，在 Platform 指定唯一公司根并级联组织标签**，  
以便 **运营激励且组织排名口径正确**。

**故事 D（内容治理）**：  
作为 **平台管理员**，  
我希望 **在文档/问答场景按扣减规则扣分**，  
以便 **违规可惩戒并可追溯**。

---

## 2. 验收标准

### 2.1 账本与手动调分

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 系统 | 任意成功记分（自动/手动） | 同事务写入 `user_point_log` 并更新 `user_point_account.balance`；流水含 `balance_after`、`delta`、`idempotency_key`（自动必填）；禁止改/删历史流水 |
| AC-02 | 平台管理员 | Portal 调整积分：非 0 整数 ∈[-10000,10000]，原因 5–100 字 | 余额可变负；写流水 `source=manual_adjust`；写审计；目标用户收站内信（代码常量模板） |
| AC-03 | 非平台管理员 | 调用调分/规则写接口 | 拒绝，错误码 `PointsPermissionDeniedError`（18201） |
| AC-04 | 运维任务 | 日对账 | `sum(log.delta)==account.balance`；不一致告警，禁止静默改流水 |

### 2.2 规则配置

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-05 | 平台管理员 | 查看规则四 Tab：获取/扣减/管理员奖励/说明文案 | 预置 G1–G4、R1–R3、M1/M4/M6 与 5 条说明文案；G5–G7、其余 M* 可作为编码新增；G7 启用后走库间 SHARE 触发 |
| AC-06 | 平台管理员 | 新增/编辑规则分值、每日上限（按**分**）、**积分受益主体**、启停 | 保存立即生效；历史流水不变；同租户同 `rule_code` 启用互斥；G1/G2/G5/G6 受益主体可选上传人/发布人；G7 可选上传人/分享人；G3/G4/M* 按编码锁定；非法选项返回 18203 |
| AC-07 | 普通用户 | 打开「积分规则」弹窗 | 仅展示启用中的获取/扣减规则 + 说明文案；**不展示 M\***；申诉相关文案为线下联系，无站内入口 |

### 2.3 自动发放

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-08 | 用户 | 文件成功进入目标库（直传或发布审批通过） | 按目标库 `space.level` 匹配 G1/G2/G5/G6；幂等键含 `file_id+target_space_id`；个人库/收藏库不计；入账用户 = 规则 `beneficiary` 解析结果（只发给一方）；**受益人**为目标库 `creator`/`admin` 则豁免（P7=B，不看操作人）；平台超管入账 skip |
| AC-09 | 用户 | 文档收藏人数达 75/150/300 | G3 补差价至当前最高档，单文档终身累计 ≤15；取消收藏再达阈值不重发；同用户对同文档收藏只计一次人数 |
| AC-10 | 提问者 | 采纳答案 | 被采纳回答者按 G4 得分（规则启用且未超日 cap）；幂等键含 `answer_id` |
| AC-30 | 用户 | 知识库间文档分享审批通过（`share_approved`，目标为其他空间） | 若 G7 启用：按获益人配置给上传人或分享人发分；幂等键 `earn:G7:{share_entry_id}`；日 cap/管理员豁免同其他 G*；**不**对外链 share-links 计分；与 PUBLISH/G1–G6 分键，同一次业务不双计 |
| AC-11 | 系统 | 触发已禁用规则或触达日 cap（按分） | 不计分；可记 `points.award.rejected` 日志；不报用户硬错误（业务主路径成功） |
| AC-12 | 平台超管用户 | 触发任意自动发放 | **跳过**；不进激励榜 |
| AC-13 | Beat | 每月 1 日 00:05（Asia/Shanghai） | 对拥有对应空间角色的用户发 M*（多角色取最高档不累加）；当月登录≥1（日活）；幂等键含 `user_id+yyyy-mm+rule` |

### 2.4 用户端与榜单

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-14 | 登录用户 | Portal 账号菜单进入「我的积分」 | 见总积分、本月获得、本月扣减、部门排名、总榜排名（>999 显示 999+）及排名刷新时间；明细可筛类型/时间；无记录时空态文案；本月窗口为上海时区当月 1 日 00:00 至当前 |
| AC-15 | 登录用户 | 查看首页积分榜 | 本月/本年/总榜 TOP10；**无**当前用户置底行；无数据空态文案；数据来自小时快照 |
| AC-16 | 系统 | 每小时刷新排行 | 写入 `point_rank_snapshot`；部门桶 = 主部门向上最近 `org_level=dept`；总榜全租户（或约定作用域）非跨租户 |

### 2.5 扣减、消息、概览

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-17 | 平台管理员 | 前台对文档/问答执行违规扣减 | 必须选择启用中的 R* 规则；写流水；通知用户 |
| AC-18 | 系统 | 积分变动 | 按**代码内常量模板**发站内信 `action_code=points_changed`，可跳转「我的积分」；无消息模板配置表/API |
| AC-19 | 平台管理员 | 查看数据概览 | 三绝对数：总发放、当前余额合计、违规扣减合计；**无环比**；约 5min 可缓存 |

### 2.6 组织四级标签

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-20 | 平台超管 | 在 Platform 指定某部门为唯一「公司」并执行级联打标 | 该公司=`company`，相对深度+1/`dept`、+2/`office`、+3 及更深=`squad`；不改 `parent_id`/`path`/用户挂载；若已存在其他 company 则拒绝 |
| AC-21 | 非超管 | 调用打标接口 | 拒绝 18201 |
| AC-22 | 系统 | 部门榜计算时主部门无向上 `dept` | 该用户部门排名展示为「—」或未参与部门榜（总榜仍可参与）；运维侧应对未打标活跃部门告警 |

### 2.7 外部同步与非功能

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-23 | 系统 | 产生积分流水 | 写入 `point_sync_outbox`（pending）；无外部配置时 Job 跳过或保持 pending，**不阻塞**记分 |
| AC-24 | 任意 | 我的积分/明细/榜接口 | P95 ≤1.5s（千人级租户） |
| AC-25 | MySQL/DM8 | 迁移与读写 | 双库可用；使用 `dialect_helpers`；禁止 MySQL 专属 JSON/ON UPDATE 假设 |

### 2.8 明确不做（反向 AC）

| ID | 说明 |
|----|------|
| AC-26 | 门户外链 `share-links` **永不**触发积分；仅库间 `SHARE`/`share_approved` 可走 G7 |
| AC-27 | 无站内申诉工单/入口 |
| AC-28 | 文档删除/审批驳回不自动冲正已发积分 |
| AC-29 | 上线前历史行为不补分 |

---

## 3. 边界情况

- 并发重复事件：依赖 `idempotency_key` 唯一约束，第二次返回已存在结果或静默成功。  
- 规则分值修改：仅影响新流水；日 cap 按「当日已得分」与新上限比较。  
- 余额为负：展示带「-」；榜单按数值排序（更负更靠后）。  
- 用户无主部门：部门排名「—」；总榜仍按余额/周期分。  
- 组织未完成唯一公司打标：部门榜降级（AC-22），积分发放不阻断。  
- 多租户：账户/流水/规则/快照均带 `tenant_id`；Beat 按活跃租户 fanout。  
- **不支持**：FIFO 过期、兑换商城、积分转让、外链分享计分、公共库管理员改全站规则。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 账本模型 | A: 仅用户字段 / B: append-only ledger + 余额缓存 | **B** | 可审计、可对账、防并发丢分（INV-11） |
| AD-02 | 事件挂钩 | A: 通用事件总线 / B: 业务成功路径显式调用 PointsService | **B** | 本仓无总线；挂钩点有限；后续可再抽 |
| AD-03 | 日上限 | A: 按次 / B: 按分 / C: 可配 | **B** | 产品拍板；实现简单 |
| AD-04 | G3 | A: 三档叠加 / B: 最高档补差价终身≤15 | **B** | 产品拍板 |
| AD-05 | 上传/发布 | A: 各计一次 / B: 进入目标库成功计一次 | **B** | 防重复激励 |
| AD-06 | 排行 | A: 实时全表 / B: 小时快照 | **B** | 对齐 PRD；可控 |
| AD-07 | 组织层级 | A: 新组织表 / B: department.org_level + 唯一公司级联 | **B** | 不改用户挂载 |
| AD-08 | 管理端 | A: Platform / B: Portal 运营 + Platform 打标 | **B** | 产品拍板 |
| AD-09 | 外部同步 | A: 阻塞上线 / B: Outbox 不阻塞 | **B** | 接口未定 |
| AD-10 | 权限 | A: 按 PRD 给公共库管理员配规则 / B: 仅超管 | **B** | 收权降风险 |
| AD-11 | 模块位置 | A: 塞进 knowledge / B: 独立 `bisheng/points` | **B** | 跨域激励，独立 DDD |

### 4.1 组织打标 Blast Radius（MUST）

| 项 | 内容 |
|----|------|
| 不变量 | 部门树拓扑与用户挂载不变；仅增加/维护 `org_level`；至多一个 company |
| 波及面 | 部门树 API/Platform UI；积分部门榜与管理端部门筛（若按标签）；依赖部门展示的报表（只读多字段，通常无害） |
| 例外路径 | 未打标节点不参与部门榜；不影响知识空间 ReBAC |
| 可行性 | 中等工作量；需超管一次性打标；回滚=清空 org_level 或迁移 down |
| 风险 | **中高**——误标导致排名桶错误；多公司误操作（接口拒绝） |
| 验证 | 指定公司后抽查四级；部门榜抽样；回归部门树 CRUD/同步 |
| 不做 | 强绑 knowledge space level；改 SSO 同步结构 |

---

## 5. 数据库 & Domain 模型

### 5.1 表

| 表 | 说明 |
|----|------|
| `user_point_account` | `user_id` UK、`balance`、`lifetime_earned`、`lifetime_deducted`、`tenant_id`、时间戳 |
| `user_point_log` | append-only：`delta`、`balance_after`、`rule_code`、`title`、`biz_type`、`biz_id`、`idempotency_key`、`source`、`operator_id`、`remark`、`occurred_at`；UK `(tenant_id, idempotency_key)` |
| `point_rule` | `rule_code`、`rule_type`(earn/deduct/admin_reward)、`name`、`score_expr`(JSON：固定或阶梯)、`daily_cap`、`beneficiary`、`status`、`remark` |
| `point_copy` | 说明文案 key + content（预置 5 条） |
| （无表）站内信文案 | 代码常量 `notify_templates.py`，不建表 |
| `point_rank_snapshot` | `period`(month/year/all)、`scope`(global/dept)、`scope_id`、`user_id`、`rank`、`score`、`balance`、`refreshed_at` |
| `point_sync_outbox` | 同步载荷、状态、重试 |
| `point_favorite_tier_award` | `file_id`、`tier`、`points_granted_total` — G3 已授档位 |
| `department.org_level` | 扩展列：`company`/`dept`/`office`/`squad`/NULL |

> 时间字段用 `UPDATE_TIME_SERVER_DEFAULT`；JSON 用 `JsonType`；大文本用 `LargeText`。

### 5.2 规则编码与 space.level 映射（计分，独立于 org_level）

| rule_code | space.level（示意） | 默认分/备注 |
|-----------|-------------------|------------|
| G1 | `public` | +3，日 cap 15 |
| G2 | `department` | +2，日 cap 10 |
| G5 | `team_ks` | 可配，默认可空/未启用 |
| G6 | `team` | 可配 |
| G3 | n/a 收藏 | 阶梯 5/10/15 |
| G4 | n/a 采纳 | +3 |
| G7 | n/a **知识库间文档分享**（`SHARE` / `knowledge_space_file_share_request` → `share_approved`） | **本期接线**；获益人可配上传人/分享人；幂等 `earn:G7:{share_entry_id}`；**不是**门户外链 |
| R1–R3 | 手动 | -100 |
| M1/M4/M6 | 公共所有者/部门管理员/科室管理员 | 200/100/50；其余 M* 可增 |

月奖角色判定：用户在对应 level 的 space 上为 `creator`（所有者档）或 `admin`（管理员档），按启用中 M* 取最高分。

### 5.3 幂等键约定（示例）

| 场景 | idempotency_key |
|------|-----------------|
| 入库计分 | `earn:{rule}:{file_id}:{space_id}` |
| G3 补差 | `earn:G3:{file_id}:tier:{tier}` |
| G4 | `earn:G4:{answer_id}` |
| G7 库间分享 | `earn:G7:{share_entry_id}` |
| 月奖 | `reward:{rule}:{user_id}:{yyyy-mm}` |
| 手动调分 | `manual:{operator}:{target}:{uuid}` |
| 前台扣减 | `deduct:{rule}:{operator}:{target}:{biz}:{uuid}` |

---

## 6. API 契约

> 前缀建议：`/api/v1/points`；组织打标可挂 `/api/v1/department/org-level` 或 points 管理子路径。  
> 认证：`UserPayload.get_login_user`；写操作校验平台超管（除用户读自己的数据）。

### 6.1 用户端

| Method | Path | 描述 |
|--------|------|------|
| GET | `/api/v1/points/me/summary` | 余额、本月获得/扣减、部门/总榜名次、`rank_refreshed_at` |
| GET | `/api/v1/points/me/logs` | 明细分页；query: type, from, to |
| GET | `/api/v1/points/rules/public` | 前台规则弹窗（无 M*） |
| GET | `/api/v1/points/leaderboard` | query: period=month\|year\|all；TOP10 |

### 6.2 管理端（Portal）

| Method | Path | 描述 |
|--------|------|------|
| GET/PUT | `/api/v1/points/admin/rules` | 规则 CRUD/启停 |
| GET/PUT | `/api/v1/points/admin/copies` | 说明文案 |
| GET | `/api/v1/points/admin/users` | 用户积分列表（搜姓名/部门、角色筛） |
| POST | `/api/v1/points/admin/users/{user_id}/adjust` | 手动调分 |
| GET | `/api/v1/points/admin/users/{user_id}/logs` | 用户明细 |
| GET | `/api/v1/points/admin/audit-logs` | 调分审计 |
| GET | `/api/v1/points/admin/overview` | 三绝对数 |
| POST | `/api/v1/points/admin/deduct` | 前台 R* 扣减 |

### 6.3 组织打标（Platform）

| Method | Path | 描述 |
|--------|------|------|
| GET | `/api/v1/departments/org-levels` | 树+标签 |
| POST | `/api/v1/departments/{id}/set-company-root` | 指定唯一公司并级联打标 |

### 6.4 请求/响应示例

**我的积分摘要**:
```http
GET /api/v1/points/me/summary
```
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "balance": 2580,
    "month_earned": 320,
    "month_deducted": 50,
    "dept_rank": 12,
    "global_rank": 38,
    "global_rank_display": "38",
    "rank_refreshed_at": "2026-08-06T14:05:00+08:00"
  }
}
```

**手动调分**:
```http
POST /api/v1/points/admin/users/1001/adjust
{
  "delta": 100,
  "reason": "月度优秀贡献奖励"
}
```
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "user_id": 1001,
    "balance": 2680,
    "log_id": 90001
  }
}
```

**明细分页**（`PageData`）:
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "title": "发布/上传文档到公共库",
        "delta": 3,
        "balance_after": 2580,
        "type": "earn",
        "occurred_at": "2026-07-29T14:32:05+08:00"
      }
    ],
    "total": 7
  }
}
```

### 6.5 错误码（182xx）

| HTTP/Body | Code | Class | 场景 | 关联 AC |
|-----------|------|-------|------|---------|
| 200 body | 18201 | PointsPermissionDeniedError | 非超管写操作 | AC-03, AC-21 |
| 200 body | 18202 | PointsInvalidAdjustError | 调分校验失败 | AC-02 |
| 200 body | 18203 | PointsRuleConflictError | 规则编码冲突/非法 | AC-06 |
| 200 body | 18204 | PointsRuleNotFoundError | 扣减规则不存在/未启用 | AC-17 |
| 200 body | 18205 | PointsCompanyRootConflictError | 公司根冲突或节点非法 | AC-20 |
| 200 body | 18206 | PointsIdempotentReplayError | 显式幂等冲突（通常内部吞掉） | AC-01, AC-08 |

---

## 7. Service 层逻辑

| 服务 | 职责 |
|------|------|
| `PointsLedgerService` | award/deduct/adjust；锁账户；写流水；日 cap；幂等 |
| `PointsRuleService` | 规则/文案/模板 CRUD；种子数据 |
| `PointsAwardFacade` | 供 knowledge/approval/qa_expert 调用的薄门面（解析规则+豁免+获益人） |
| `PointsRankService` | 小时聚合写快照；读榜/读个人名次 |
| `PointsMonthlyRewardService` | Beat 月奖 |
| `PointsNotifyService` | 代码常量模板渲染 + `MessageService.send_message` |
| `DepartmentOrgLevelService` | 唯一公司根 + 级联打标（Platform） |
| `PointsSyncOutboxService` | 写 outbox；drain Job（外部未就绪则 no-op） |

### 挂钩点（修改方，只增加调用，不夺所有权）

| 业务成功点 | 调用 |
|------------|------|
| 空间文件上传成功（非 personal/favorite） | `AwardFacade.on_space_file_ready` |
| 发布审批 outbox 执行成功 | 同上（目标库） |
| 收藏创建 | `on_favorite_changed` → 可能 G3 |
| 问答采纳 | `on_answer_adopted` |
| 审批 `share_approved`（G7） | `PointsAwardFacade.on_document_shared(...)`；勿挂外链 |
| 不挂钩 | 外链 share-links、删除冲正 |

### 权限

- 读自己的积分：登录即可。  
- 管理写：`UserPayload` 超级管理员 / 平台管理员判定（与现网 admin 一致，具体对齐 `is_admin`/`super_admin` 实现）。  
- **不**给公共库管理员规则写权限。  
- 资源创建若产生新积分实体无需 OpenFGA 资源元组（积分非 ReBAC 资源）；账户按 user 隔离。

---

## 8. 前端设计

### 8.1 Portal（兄弟仓 `shougang-group-knowledge-portal`）

| 页面 | 说明 |
|------|------|
| Header 账号菜单 | 「我的积分」入口 |
| `/points` 或抽屉页 | 统计卡片 + 明细 + 规则弹窗 |
| `HomePage` | 替换 `POINTS_PODIUM`/`POINTS_ROWS` mock 为 API；去掉「我」行 |
| `AdminPage` | 新菜单：积分概览、规则、用户、审计 |

状态：沿用 Portal 现有方案；HTTP 经 BFF 或直连 BiSheng（与现网门户一致，BFF 若需代理则加路由）。

### 8.2 Platform

| 页面 | 说明 |
|------|------|
| 部门树管理 | 「设为公司根并级联打标」；展示 org_level 徽章；仅超管可见操作 |

### 8.3 Client（可选）

- 文档列表/阅读、专家问答删除弹窗：平台管理员可见「积分扣减」→ 调 `admin/deduct`。  
- **不做**「我的积分」入口。

---

## 9. 文件清单

### 新建（BiSheng）

| 文件 | 说明 |
|------|------|
| `bisheng/points/**` | api / domain models / repositories / services |
| `bisheng/common/errcode/points.py` | 182xx |
| `bisheng/core/database/alembic/versions/*_points.py` | 表 + `department.org_level` |
| `bisheng/worker/points/*.py` | 排行、月奖、对账、sync drain |
| `test/points/**` | 账本幂等/cap/豁免/G3/月奖/打标 |

### 修改（BiSheng）

| 文件 | 变更 |
|------|------|
| `api/router.py` | 注册 points 路由 |
| `core/config/settings.py` | Beat 任务 |
| `database/models/department.py` | `org_level` 字段 |
| knowledge / approval handler / qa_expert / favorite | 成功路径调用 AwardFacade |
| message 侧 | 仅被调用，不改所有权 |

### 新建/修改（Portal / Platform）

| 位置 | 变更 |
|------|------|
| Portal Header / HomePage / AdminPage / points 页 | 用户端+运营台 |
| Platform 部门树 | 打标 UI |

---

## 10. 非功能要求

- **性能**：读接口 ≤1.5s；排行小时批；概览可 5min 缓存。  
- **安全**：超管写；审计不可删；无密钥入仓；调分强审计。  
- **可观测**：`points.award.*`、`rank.refresh`、`balance.mismatch`、`sync.*`。  
- **时区**：Asia/Shanghai。  
- **兼容**：不影响未启用积分挂钩时的主业务（AwardFacade 内部吞拒绝原因，主流程成功）。  
- **备份**：流水表纳入现有 DB 备份策略（运维），应用层不实现「删审计」。

---

## 11. Celery Beat

| 任务 | Cron（上海） | 说明 |
|------|-------------|------|
| `points.refresh_rank_snapshots` | `5 * * * *` | 小时榜 |
| `points.monthly_admin_rewards` | `5 0 1 * *` | 月奖 |
| `points.reconcile_balances` | `30 2 * * *` | 对账 |
| `points.drain_sync_outbox` | `0 3 * * *` | 外部同步（可空转） |

---

## 相关文档

- **后端设计**: [design.md](./design.md)（表/索引/迁移、Request/Response、Mermaid 时序与状态机、生产升级）  
- 版本契约: [../release-contract.md](../release-contract.md)（INV-11~14，模块 182）  
- 需求分析决议: [../../../docs/PRD/积分系统/积分系统需求分析-V1.1.md](../../../docs/PRD/%E7%A7%AF%E5%88%86%E7%B3%BB%E7%BB%9F/%E7%A7%AF%E5%88%86%E7%B3%BB%E7%BB%9F%E9%9C%80%E6%B1%82%E5%88%86%E6%9E%90-V1.1.md) §11  
- PRD 抽取: [../../../docs/PRD/积分系统/PRD-V1.1-extracted.md](../../../docs/PRD/%E7%A7%AF%E5%88%86%E7%B3%BB%E7%BB%9F/PRD-V1.1-extracted.md)  
