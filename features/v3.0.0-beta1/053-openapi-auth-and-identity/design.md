# Design: 开放 API 鉴权与身份传递（全量：P0 底座 · P1 身份传递 / 个人访问令牌 / 日常模式会话 · P2 运营能力）

> **本文档定位 — 总体设计 + 分工边界（Why this How）**
>
> - 需求的 **What** 在上游 PRD（`docs/product/3.0 开放 API 鉴权与身份传递 PRD.md` **v2.4**，2026-08-27/28）：§4 是需求正文、§5 是验收标准（AC-1～50、AC-P1～P22）。本 Feature **不另写一份复述 PRD 的 spec.md**，`spec.md` 只登记范围裁定与 PRD 之外的补充 AC（share-token、P2 细则）。
> - 本文回答 **怎么做、为什么这么做、谁做哪块、接口在哪对齐**。7 个工作流（WS-A～G）可由不同人并行，§4 是分工总表，§6 是所有人必须对齐的共享契约。
> - 底座部分（凭据 / 服务账号 / 管理界面 / 端点接入 / share-token）**沿用 `3.0-vibe` 的 049 设计**（`reference/vibe-049-design.md`，D1–D13 决策 + 27 条坑），本文只写差异与增量，不重抄；引用格式 `vibe-049 D5` / `vibe-049 坑 14`。
> - 调整原则见 `docs/SDD-Guide.md` §3–§4：实现变化 → 覆盖本文、只留今天的状态；推翻已 ★ 确认的决策 → 停下重新确认。
>
> **代码事实口径**：`feat/3.0.0-beta1` @ `972397fbe`（2026-08-31 核实）；vibe 侧 `3.0-vibe` @ `b63a320f2`+。`文件:行号` 会漂移，符号名不会——落地前以符号名重定位。

**关联**: [discovery.md](../000-openapi-auth-discovery/discovery.md) · [spec.md](./spec.md) · [tasks.md](./tasks.md) · [release-contract.md](../release-contract.md) · [reference/](./reference/README.md)
**版本**: v3.0.0-beta1 · **Feature 编号**: F053 · **最后更新**: 2026-08-31（初版，待 ★ 用户确认）

---

## 0. 阅读路径（按角色）

| 你是 | 先读 | 再读 |
|---|---|---|
| 把控者 / 评审 | §1 目标范围 · §3 总体架构图 · §4 分工总表 | §6 共享契约 · §10 发布 |
| WS-A 底座与端点接入 | §4 · §5.A · `reference/vibe-049-design.md` 全文 | §6 · §8 坑 |
| WS-B 管理界面（platform） | §4 · §5.B · §6.2 API 契约 | vibe-049 design §4.3 platform 行 |
| WS-C 身份传递 | §4 · §5.C · `reference/vibe-050-spec.md` §3–§4 | §6.1 Principal · §6.3 错误码 |
| WS-D 个人访问令牌 | §4 · §5.D · PRD §4.10 全文 | §6 · §8 |
| WS-E 日常模式会话 | §4 · §5.E · PRD §4.6.3 · `reference/vibe-058-spec.md` §4 | §6.2 |
| WS-F P2 运营能力 | §4 · §5.F · PRD §4.8 | §6.3 · §8 |
| WS-G share-token 通道 | §4 · §5.G · vibe-049 D8 | §6.2 |

---

## 1. 目标与范围

**目标**：给 `/api/v2/**` 建立唯一一条凭据校验管线——凡调用必持密钥、密钥必绑主体、身份必显式声明——并把匿名超管通道彻底关掉；在同一管线上交付两类主体（服务账号 `bs-sak-` / 自然人 `bs-pat-`）、两种身份模式（自身 S / 代表他人 D）、日常模式会话的对外开放，以及按密钥的限流 / 配额 / IP 白名单 / 幂等。

**范围（按 PRD 需求编号）**：

| PRD | 需求 | 阶段 | 归属工作流 |
|---|---|---|---|
| R1 | 凭据体系 | P0 | **WS-A**（移植 vibe 底座）；P2 属性列由 WS-F 追加 |
| R4 | 服务账号主体（含资源归属人） | P0 | **WS-A** |
| R5 | 端点接入（38 HTTP + 2 WS、6 端点不暴露、4 处既有缺陷） | P0 | **WS-A**（HTTP）+ **WS-G**（WS 与分享页） |
| R6 | 管理界面（服务账号 / 密钥 / 资源授权） | P0 | **WS-B** |
| R9 | 升级须知（零迁移、移除 `default_operator` / `enable_guest_access`） | P0 | **WS-A** + 发布说明 |
| R3 铁律 1–3 | 无凭据拒绝 / 缺身份报错 / 评估失败报错 | P0 | **WS-A** |
| R2 / R3 委托 / R7 | 两种身份模式、外部用户标识头、五道准入、审计双归属、裸 `user_id` 收口、检索文件级过滤 | P1 | **WS-C**（后端）+ **WS-B**（委托配置区 UI） |
| R10 | 个人访问令牌（自然人主体、自助签发、级联失效、治理三闸门、技能包） | P1 | **WS-D**（后端 + client）+ **WS-B**（管理员台账 / 开关 UI） |
| §4.6.3 | 日常模式会话开放（`chat:invoke` 的消费端点） | P1 | **WS-E** |
| R8 | 限流 / 配额 / IP 白名单 / 幂等 | P2 | **WS-F**（后端）+ **WS-B**（签发表单网络组） |
| §4.6.1 浏览器直连 | share-token 通道（两个免登录分享页） | P0 附带 | **WS-G** |

**非目标**（PRD §六原样继承）：密钥级资源白名单、完整 OAuth 2.0、最终用户令牌透传、即时建号、`/api/v1` 鉴权改造、按单个端点的细粒度权限、第二套并行会话契约、Webhook 回调方向鉴权、任务模式（灵思）与异步执行（明确报错留位）；PAT 本期只开 `knowledge:read`。**应用工场三面（MCP / 模型协议面 / CLI）不在 beta1**——三扩展位代码随底座原样移植但 `open_platform.enabled` 默认关、不建三面（讨论见 §2.2）。

**发版约束**：WS-A 与 WS-C 必须**同版发布**（PRD §4.9：裸 `user_id` 随本版一并移除、不留过渡期；WS-A 单独上线时仍留有一条经参数指定身份的残余路径）。其余工作流可各自晚于该基线合入。

---

## 2. 关键约束

> 全局铁律（DDD 分层 / 双 DB / 多租户自动注入 / 权限唯一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP）遵循 `docs/constitution.md` C1–C7，不重抄。**vibe-049 K1–K12 全部沿用**（撤销 5 秒内主动失效、fail-closed、有效性单一判据、v2 面真 HTTP 状态、DM8 双库、密钥表禁批量写、多节点默认、开关三段式、凭据校验先于租户上下文且必须覆盖 ContextVar、错误码 260 段）。以下只写本 Feature 新增的。

| # | 约束 | 出处 / 后果 |
|---|---|---|
| K13 | **一条管线、固定顺序**（§3 图）：凭据 → 租户 → 能力开关 → IP → 权限位 → 身份模式与准入 → 限流配额 → 构造身份 → 业务。任何工作流新增的检查只能**插进既定槽位**，不得另起第二条校验路径或在端点体内补判 | AC-1 / AC-29「不存在绕过该路径的端点」；分工并行的前提 |
| K14 | **主体解析按 `subject_kind` 分派**（`SUBJECT_RESOLVERS` 注册表）：新主体 = 新枚举值 + 新解析函数，不改表、不改管线 | PRD 附录 E.6；WS-D 只注册 `natural_person` |
| K15 | **模式 D 是纯替换**：执行身份整个换成被代表用户，服务账号自身授权不参与；**被代表用户的身份构造与准入检查 3 都以权限运行时的系统级放行谓词为准**（`PermissionActor.super_admin` / `tenant_admin_tenant_ids` 的计算源） | PRD §7.2 / vibe-050 §3；判漏 = 一把窄权限密钥换到管理员无界权限，全 Feature 最重单点 |
| K16 | **PAT 权限动态继承、不做快照**；管理员短路照常，但可见租户集合恒按密钥所属租户计算，`super_admin` 不放开租户过滤 | PRD §4.10.3 / §4.10.4 / D17；`_visible_tenant_ids` 副本对任何主体都按密钥租户算 |
| K17 | **静默降级零容忍**：异步 → `26015`、任务模式 → `26017`、未知工具类型 → 400 指名、契约外字段 → 400 指名、`delegate` 漏头 → `26016`。**不存在**「接受了但不生效」的字段 | PRD §4.6.3 三.2 / AC-34 / AC-35 / AC-38 / AC-50 |
| K18 | **P2 检查全部 fail-closed**：Redis 不可用时限流 / 配额 / 幂等一律拒绝（`26030` 503），不沿用部门并发槽位那条 fail-open 原语 | PRD 附录 E.5 |
| K19 | **审计双归属是硬要求**：逐调用记录同时含 actor（密钥）与 subject（以谁名义）；模式 S 的 subject 为空、外部标识另列 | PRD §4.4.5 / §4.8.1 / AC-23 / AC-P13 |
| K20 | **同一能力一套契约**（D12）；日常模式会话用平台自有命名，不冒用第三方契约的名字 | PRD §4.6.3 五 / vibe-058 决议-6 |
| K21 | **对客文档改名**：「服务账号模式」→「自身身份模式」，随 WS-D 交付（AC-P22）；对外一律用中文名不用 S / D 字母 | PRD §4.10.8 / 附录 F |

**Constitution Check（自查）**：C1 新模块 `open_api/` 按 `api/ + domain/` 分层，v2 端点只 import `open_api.domain.scopes`（domain 级）；C2 全部 Alembic 变更列于 §7、新表 `create_all`、`VARCHAR` 不用 `CHAR`、JSON 列不在 SQL 里按位过滤；C3 密钥表 / 委托范围表 / 调用日志表物理带 `tenant_id` 并注册 `_TENANT_AWARE_MODEL_MODULES`，按哈希查凭据在 `bypass_tenant_filter()` 下、校验后无条件 `set_current_tenant_id`；C4 授权写路径只经 F048 runtime、反查走 SQL 投影账本、模式 D 不改 `PermissionActor` 只换入参；C5 错误码 260 段登记（§6.3）；C6 明文不落盘不进日志、幂等缓存不存请求头；C7 前端只经 `controllers/API/`（platform）/ `~/api`（client）。

### 2.2 与 vibe 底座的差异清单（移植时逐条处理）

| # | vibe-049 的写法 | beta1 上的处置 | 责任 |
|---|---|---|---|
| 1 | 排除项「个人访问令牌整条否决；全平台只有服务账号一类主体」 | **作废**（PRD D13）。`credential_service.issue` 与 `credential_validator` 的前缀提取按 `subject_kind` 参数化（附录 E.6 两处约 5 行） | WS-A 移植时即改，WS-D 消费 |
| 2 | 三扩展位 `model:invoke` / `identity:read` / `app:manage` 的运行期消费随 F051–F053 | **三面不建**。注册表保留、`requires_open_platform=True`、`open_platform.enabled` 默认 `false` → 表单不出现、签发被拒（`26023`）。**不删**：零成本且避免日后与 vibe 合并冲突 | WS-A |
| 3 | `hosted_app` 主体（托管应用运行期凭据） | 不注册解析器、不登记 kind；`subject_kind` 仍是可扩展枚举 | WS-A |
| 4 | 「服务账号详情页接入信息区（MCP 地址 / CLI）」 | 不做 | WS-B |
| 5 | 「文件级检索过滤随 F052 统一检索门面」 | beta1 无 F052 → **WS-C 直接改两个检索分支**（§5.C.6） | WS-C |
| 6 | 「HTTP 逐调用审计本期只落结构化日志，表化随 F050」 | 表化随 **WS-C**（§5.C.5），WS-A 期先落 `open_api.call` 日志行 | WS-A → WS-C |
| 7 | `api_credential` / `service_account` 无 Alembic、靠 `create_all` | **补 Alembic revision**（§7）——beta1 已有生产客户，`create_all(checkfirst)` 只对空库友好 | WS-A |
| 8 | D13 MVP-114 纵切 Wave 划分 | 不适用；本文 §4 按工作流重排 | — |
| 9 | 错误码 `26004` 在 F049 期借作「身份传递能力尚未启用」 | 同样借用；WS-C 上线后收窄为「未授予委托 / 不在范围」（vibe-050 决议-4） | WS-A → WS-C |
| 10 | vibe 提交携带的 `features/v3.0.0/049-*` 文档 | 不搬（已拷入 `reference/`）；`docs/constitution.md` C5 登记表改动**要搬** | WS-A |

---

## 3. 总体架构

### 3.1 请求处理管线（`/api/v2/**`，HTTP 与 WebSocket 同一函数 `verify_open_api_access`）

```
                 Authorization: Bearer bs-sak-… / bs-pat-…        ?share_token=…（仅 2 个 WS）
                                   │                                      │
  ┌──① 提取凭据 ───────────────────┴──────────────────────────────────────┘
  │   无 / 格式非法 → 401 26001                                                    [WS-A · WS-G]
  │
  ├──② 凭据校验（Redis 3s 缓存 → miss 时 bypass 查 api_credential）
  │   sha256 → 恒时比较 → 未撤销 → 未过期 → SUBJECT_RESOLVERS[subject_kind](…)
  │     service_account : 主体存在 ∧ user_type=service ∧ 未停用/删除 ∧ 活跃租户==密钥租户      [WS-A]
  │     natural_person  : 存在 ∧ delete=0 ∧ user_type=human ∧ 活跃租户==密钥租户 → 26043      [WS-D]
  │     share_link      : ACTIVE ∧ 未过期 ∧ share_scope=app ∧ resource_id==路径 id             [WS-G]
  │   失败 → 401 26002 / 26043 / 26027；Redis/DB 异常 → 503 26030（fail-closed）
  │
  ├──③ 租户：DISABLED_TENANT_KEY 黑名单 → set_current_tenant_id(密钥租户) + set_visible_tenant_ids({leaf,1}|{1})
  │        ★ 对任何主体都按密钥租户算，超管 PAT 也不放开（K16）                                 [WS-A · WS-D]
  │
  ├──③′ 限流（凭据一旦解析成功即计，按 credential_id 令牌桶）：超限 → 429 26009                  [WS-F]
  │     ★ 放在权限位 / 准入之前：随后被 403 拒绝的请求也计入，防止用错误请求探测；无有效凭据的请求
  │       没有计量维度、不计（它们在 ② 已 401）
  │
  ├──④ 能力开关（仅 natural_person）：部署级 ∧ 租户级，任一关 → 403 26040                        [WS-D]
  │
  ├──⑤ IP 白名单（凭据配置了 ip_allowlist 时）：来源 IP ∉ CIDR → 403 26008                      [WS-F]
  │
  ├──⑥ 权限位：读 conn.scope["endpoint"] 上的 @open_api_scope 标记
  │   无标记 → 500 26031 │ scope=None → 跳过 │ 缺位 → 403 26003 (data.required=缺哪位)         [WS-A]
  │
  ├──⑦ 身份模式与准入（读 X-Bisheng-On-Behalf-Of / X-Bisheng-End-User）                          [WS-C]
  │   两头并存 → 400 26010 │ End-User 超限/不可打印 → 400 26018
  │   有 OBO：凭据无 delegate → 403 26004；PAT → 403 26004（文案「个人密钥不支持委托」）
  │           五道准入：①delegate ②目标自然人/存在/未禁用/同租户(26005 无差异) ③非超管非租户管理员(26007)
  │                    ④在委托范围内(26004) ⑤端点 modes 含 D(26006)  → 模式 D，effective_user=目标
  │   无 OBO：凭据持 delegate → 400 26016（不落回 S）；否则 模式 S，effective_user=主体
  │           （End-User 头：session=True 的端点写分区键；缺省记 WARN；无会话语义端点只留审计）
  │   （WS-A 期：任一身份头存在 → 403 26004，WS-C 上线后替换为本槽位）
  │
  ├──⑧ 日配额（按 credential_id，只对通过 ①–⑦ 的请求计数）：超限 → 429 26009                     [WS-F]
  │
  ├──⑨ 构造身份：UserPayload(effective_user) + OpenApiPrincipal → ContextVar + conn.scope        [WS-A · WS-C · WS-D]
  │   service_account : is_global_super=False, user_role=[]（不调 init_login_user，vibe-049 D2）
  │   natural_person  : 取角色 + _check_is_global_super（管理员短路照常，K16），写入凭据缓存载荷
  │   模式 D 目标     : 同 natural_person 构造；检查 ③ 已保证非特权
  │
  ├──⑩ 幂等（仅 idempotent=True 的端点，Idempotency-Key 头）：命中 → 直接返回首次响应；
  │      同键在途 → 409 26011；同键不同请求体 → 409 26011                                     [WS-F]
  │
  ├──⑪ 最后使用时间节流写（SET NX EX 60 + 单行 UPDATE）                                       [WS-A]
  │
  ▼  端点体：Depends(get_open_api_login_user) → 业务 Service → F048 require_business_action
     （资源级失败回业务既有错误码，与 26003 可区分；FGA 不可用 → 503，铁律 3）
     创建类端点：模式 S → owner=资源归属人 + 回授服务账号（vibe-049 D5）；模式 D → owner=被代表用户、不回授
  ▼
  ⑫ 响应后（纯 ASGI 中间件，只挂 /api/v2 前缀）：读 conn.scope["open_api_principal"] → 逐调用审计入队
     （actor=凭据/主体 · subject=被代表用户 · end_user · endpoint · status · ip · latency）        [WS-C]
```

### 3.2 模块图

```
bisheng/open_api/                          ← 新模块（WS-A 移植 + 各 WS 增量）
├─ api/
│  ├─ dependencies.py        verify_open_api_access / open_api_subject(scope) / get_service_account_admin
│  ├─ exception_handlers.py  /api/v2 真 HTTP 状态；WS → WebSocketException(1008)
│  ├─ middleware.py          [WS-C] 调用审计 ASGI 中间件（只挂 /api/v2）
│  ├─ idempotency.py         [WS-F] Idempotency-Key 依赖
│  ├─ router.py              /api/v1/service-accounts · /api/v1/personal-tokens · /api/v1/me/api-token · /api/v2/auth
│  └─ endpoints/
│     ├─ auth.py                     GET /api/v2/auth/whoami
│     ├─ service_account.py          [WS-A] CRUD / 启停 / 删除
│     ├─ service_account_keys.py     [WS-A] 签发 / 编辑 / 撤销 / 批量撤销 / scopes 目录；[WS-C] 委托范围；[WS-F] ip/限流字段
│     ├─ service_account_grants.py   [WS-A] 主体侧授权页读 + mutate + revoke-all
│     ├─ personal_token_self.py      [WS-D] 员工自助：GET/POST/DELETE /api/v1/me/api-token · install-prompt
│     ├─ personal_token_admin.py     [WS-D] 台账 / 强制吊销 / 租户开关与 TTL
│     └─ skill_pack.py               [WS-D] GET /api/v1/open-api/skills/{pack}.zip（匿名）
├─ domain/
│  ├─ scopes.py              OPEN_API_SCOPES 注册表 + @open_api_scope(scope, modes, session, allow_share_token, idempotent)
│  ├─ context.py             OpenApiPrincipal（§6.1）+ ContextVar
│  ├─ models/
│  │  ├─ api_credential.py           [WS-A] + [WS-F] ip_allowlist / rate_limit_rpm / quota_daily_calls 列
│  │  ├─ service_account.py          [WS-A]
│  │  ├─ credential_delegate_scope.py [WS-C] 委托范围条目
│  │  ├─ open_api_call_log.py        [WS-C] 逐调用审计
│  │  └─ open_api_tenant_setting.py  [WS-D] 租户级 PAT 开关 / TTL
│  ├─ services/
│  │  ├─ credential_service.py       [WS-A] issue/update/revoke/revoke_by_subject/touch/expire
│  │  ├─ credential_validator.py     [WS-A] 8 步校验 + SUBJECT_RESOLVERS；[WS-D] natural_person 解析器
│  │  ├─ service_account_service.py  [WS-A]
│  │  ├─ identity_service.py         [WS-C] 身份头解析、五道准入、模式分流、目标身份构造
│  │  ├─ delegate_scope_service.py   [WS-C] 范围 CRUD + 保存期自然人校验 + department 子树判定
│  │  ├─ call_audit_service.py       [WS-C] 审计队列 + 批量落库
│  │  ├─ personal_token_service.py   [WS-D] 一人一把、重新获取、级联失效、台账、开关
│  │  ├─ skill_pack_service.py       [WS-D] zip 内存打包（Base URL / 白名单在下发时填）
│  │  ├─ rate_limit_service.py       [WS-F] 令牌桶 Lua + 日配额
│  │  └─ idempotency_service.py      [WS-F]
│  └─ schemas/…
├─ skill_packs/bisheng-knowledge-search/   [WS-D] SKILL.md · meta.json · references/api.md · scripts/
bisheng/open_endpoints/                    ← 既有 v2 端点：加标记、身份改 ContextVar、删 chat.py           [WS-A]
bisheng/workstation/… + open_endpoints/api/endpoints/workbench.py   ← 日常模式会话 V2 面                  [WS-E]
bisheng/share_link/                        ← share_scope 列、作用域端点、/app-shares 管理端点               [WS-G]
bisheng/worker/open_api/tasks.py           ← Beat：到期兜底 [WS-A]、调用日志清理 [WS-C]
platform: pages/SystemPage/components/ServiceAccount/  [WS-B]；PersonalToken/  [WS-B]
client:   layouts/UserPopMenu → PersonalTokenDialog     [WS-D]；pages/standaloneChat 带 share_token [WS-G]
```

### 3.3 关键模块职责（做什么 / 不做什么）

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `open_api/api/dependencies.py` | 管线 ①–⑪ 的唯一入口；HTTP / WS 同函数；写 ContextVar + `conn.scope` | 不判具体资源权限（交 F048）；不解析业务参数；不写审计（交中间件） |
| `open_api/api/middleware.py` | 响应后取 `conn.scope["open_api_principal"]` 入审计队列 | 不做任何拒绝决策；principal 缺失（① 就 401 的请求）也记一条、subject 为空 |
| `open_api/domain/services/credential_validator.py` | 凭据校验 8 步 + `SUBJECT_RESOLVERS` 分派 + 缓存 | 不认识端点、不判权限位、不解析身份头 |
| `open_api/domain/services/identity_service.py` | 身份头解析、五道准入、目标身份构造 | 不读端点体、不改 `PermissionActor` 结构、不做资源级判定 |
| `open_api/domain/services/personal_token_service.py` | 一人一把 / 重签 / 删除 / 台账 / 开关读写 / 级联失效入口 | 不签发服务账号密钥（走 `credential_service`）；不判权限 |
| `open_api/domain/services/rate_limit_service.py` · `idempotency_service.py` | Redis 侧计量 / 快照 | 不落库、不做业务判断；Redis 异常向上抛 `26030` |
| `open_api/domain/services/call_audit_service.py` | 有界队列 + 批量落库 + 清理 | 不阻塞请求；不做统计聚合（查询面另立） |
| `open_api/domain/services/skill_pack_service.py` | 仓内目录 → 内存 zip，渲染 Base URL / 白名单 | 不管理版本、不做 CLI 分发（那是 vibe `dev_toolkit`） |
| `open_endpoints/api/endpoints/*.py` | 打标记、身份改 `Depends(get_open_api_login_user)`、业务调用 | 不再解析任何身份 / 配置身份；不 import `open_api.api.*`、`workstation.api.*` |
| `workstation/domain/services/chat_service.py` `run_daily_turn` | 产内部 `TurnEvent` 流，供工作台 SSE 与 V2 SSE 两个适配器 | 不知道 V2 契约字段名；不做入参清洗（适配器做） |
| `share_link/`（WS-G） | share-token 校验、作用域端点、`/app-shares` 管理 | 不出现在 v2 HTTP 面；不承载身份头 |
| platform `SystemPage/components/{ServiceAccount,PersonalToken}/` | 管理界面 | 不直连 HTTP（C7）；不硬编码权限位清单（走 `GET /scopes`） |
| client `PersonalTokenDialog.tsx` | 员工自助面 | 不展示他人令牌；开关关时不渲染入口 |

---

## 4. 工作流拆分与分工

> **并行原则**：WS-A 是地基，其 **Wave 1（移植，约 2 天）** 落地后其余六个工作流即可并行；各工作流之间只通过 §6 的共享契约耦合，不共享未定义的代码。每个工作流自带 tasks（`tasks.md` 按 WS 分节）、自带测试、各起一条分支 `feat/v3.0.0-beta1/053-ws-<x>-<name>`，合回 `feat/v3.0.0-beta1/053-openapi-auth-and-identity` 集成分支。

| WS | 名称 | 范围（交付物） | 前置 | 与谁对接 | 人力 / 估算 |
|---|---|---|---|---|---|
| **A** | 底座移植 + 存量端点接入 | ① cherry-pick vibe 5 提交 + 解冲突 + 补 Alembic（Wave 1）；② 38 端点打标 + router 级依赖抬到 `router_rpc` + 删 6 个 `/chat/*` + 删 `get_default_operator*` + `resolve_operator` 收紧 + `default_operator` / `enable_guest_access` 移除；③ 4 处既有缺陷（未上线校验 / stop 归属 / `download_statistic` 收口 / 助手 WS 裸崩）；④ 资源归属人接缝（vibe D5 三条创建路径）；⑤ 对账豁免 / 配额排除 / 管理接口拒绝矩阵；⑥ 到期 Beat 兜底；⑦ `open_api.call` 结构化日志；⑧ 主体侧授权读端点 + mutate 编排（后端） | 无 | 向所有 WS 提供 §6.1 Principal、`@open_api_scope`、`SUBJECT_RESOLVERS`、管理端点 | 后端 1 人 · **7～8 人天**（Wave 1 = 2 天） |
| **B** | 管理界面（platform） | ① 移植 vibe 8 个组件（列表 / 新建 / 概览 / 密钥 / 签发 / 明文弹窗）并对齐 beta1 设计规范；② 「资源授权」tab（反查列表、来源列、全部撤销排除回授、AC-64 提示、`delegate` 存在时的显著提示）；③ 签发 / 编辑表单「委托配置」分组（范围选择 user+department、必填、互斥硬阻断、风险提示）；④ 「个人访问令牌」管理员台账 tab（元数据、单个 / 按人吊销、租户开关 + 默认 TTL、部署级未开置灰说明）；⑤ 签发表单「网络」组（IP 白名单 CIDR、限流 rpm、日配额）；⑥ 审计页 lockstep（action 枚举三语）；⑦ `ApiAccess*.tsx` 示例改 `bs-sak-`、`ChatLink` 免登录 URL 带 share_token | A Wave 1（管理端点契约 §6.2） | A / C / D / F 各自的管理端点 | 前端 1 人 · **8～10 人天** |
| **C** | 身份传递 | ① 身份头解析 + 模式分流 + 五道准入（`identity_service`）；② 委托范围表 + 保存期校验 + department 子树调用期展开；③ 端点 `modes` 声明落地（附录 B.1 允许模式列；仅 S：`download_statistic`、asr / tts）；④ 两个 WS 握手期准入；⑤ `MessageSession.external_user_id` + `ChatMessage` 冗余 + DAO 过滤参数（只写不读）；⑥ 逐调用审计表 + ASGI 中间件 + 批量落库 + 清理 Beat；⑦ 裸 `user_id` 收口（6 端点 → `26019`）+ `add_relative_qa` 死参数；⑧ `POST /filelib/retrieve` 补文件级过滤（两个检索分支）；⑨ 定义 6 与模式 D 的优先级（模式 D 不回授）；⑩ `26004` 语义收窄 + 错误码 26005–26007 / 26010 / 26016 / 26018 / 26019 三语 | A Wave 1 | B（委托配置区）· E（消费模式分流与分区键）· D（PAT 拒 OBO） | 后端 1 人 · **12～14 人天** |
| **D** | 个人访问令牌 | ① `natural_person` 解析器（角色 + 超管探测入缓存载荷；租户不放开）；② 一人一把签发 / 重新获取 / 删除（`personal_token_service`）+ 白名单校验（只 `knowledge:read`，`26041`）+ 租户默认 TTL（`26042`）；③ 级联失效三触发点（禁用 / 删除 / 换租户）+ 校验期兜底（`26043`）；④ 两层开关（Settings + `open_api_tenant_setting` 表）+ `26040`；⑤ 管理员台账 / 强制吊销端点；⑥ 技能包 `bisheng-knowledge-search`（SKILL.md / meta.json / api.md / 请求脚本 / 安全声明）+ zip 分发端点 + 安装提示词端点（动态 Base URL）；⑦ client 个人中心「API 令牌」弹窗（获取 / 状态 / 删除 / 重新获取 / 明文一次 / 安装提示词 / curl 示例）；⑧ 对客文档改名「自身身份模式」 | A Wave 1；检索文件级过滤依赖 C-⑧（AC-P7） | B（台账 / 开关 UI）· C（文件级过滤） | 后端 1 人 + client 前端 0.5 人 · **12～15 人天** |
| **E** | 日常模式会话开放 | ① V2 契约（§5.E：`POST /api/v2/workbench/chat` · `GET /api/v2/workbench/turns/{id}` · `POST /api/v2/workbench/files`）；② 入参清洗（9 个死字段、`clientTimestamp` 改可选）+ 白名单式拒绝（契约外 400 指名）；③ 复用 `stream_chat_completion` 的适配层：模型按名解析、知识库 / 平台工具 / 附件 / 业务上下文指令映射；④ 语义可分的 SSE 事件 + 非流式聚合；⑤ 归属校验（模式 S 分区键 / 模式 D 被代表用户，不匹配 404）；⑥ `26015` / `26017` 留位；⑦ 对外文档逐项；⑧ 清 `chat:invoke` 的 `pending_note_key` | A Wave 1 + C（模式 D 主场，不可只出 S 版本） | C（分区键 / 归属）· B（无 UI） | 后端 1 人 · **8～10 人天**（D9 改判后已下调） |
| **F** | P2 运营能力 | ① 凭据表加 `ip_allowlist` / `rate_limit_rpm` / `quota_daily_calls`；② 令牌桶 Lua（fail-closed）+ 日配额计数；③ IP 白名单（来源 IP 取值规则）；④ 幂等键（`idempotent=True` 端点：`workflow/invoke`、`workbench/chat` 非流式、`filelib/add_qa`）；⑤ 429 / 26008 / 26009 / 26011 三语；⑥ 管理端点字段透传 | A Wave 1 | B（表单网络组）· E（幂等挂到 chat 端点） | 后端 1 人 · **6～8 人天** |
| **G** | share-token 通道 | vibe-049 D8 全部：`share_link.share_scope` 列 + 相对秒有效期强制 + 撤销端点；3 个匿名作用域端点（豁免前缀）+ `/api/v1/app-shares` 登录态管理端点（非豁免前缀）；两个 WS 接受 `?share_token=` + 3s watchdog；client guest 页改造（不再打任何 v2 HTTP）；platform `ChatLink` URL | A Wave 1 | A（WS 依赖同函数）· B（`ChatLink`） | 全栈 1 人 · **5～6 人天** |

**关键路径**：A-Wave1（2d）→ A-②③ 与 C-①② 并行 → C-⑧ 文件级过滤（D 的 AC-P7 前提）→ E（依赖 C 模式分流）。总工期以 3 后端 + 1.5 前端 并行计约 **3～4 周**。

**集成里程碑**：
- **M1（A Wave 1 落地）**：beta1 上 `GET /api/v2/auth/whoami` 用 `bs-sak-` 通、平台可建号发钥；其余 WS 开工。
- **M2（A + C + G 完成）**：全端点鉴权、模式 D 可用、分享页不断 → **可对外发版的最小集**。
- **M3（B + D 完成）**：管理界面完整、PAT 端到端（装包 → 配密钥 → 提问）。
- **M4（E + F 完成）**：日常模式会话开放、限流 / 幂等。

---

## 5. 各工作流设计

### 5.A 底座移植与存量端点接入

**决策 A1：整体 cherry-pick，不重写。** 顺序 `a15f06135 → 86e52f90b → 43e73bfc5 → c5989ffd6 → e31c35732`（已在临时 worktree 实测：85 文件 / +10.5k 行；真冲突只有 `api_errors` 三语 × 3 处生成物、`api/v1/endpoints.py get_env`、`test_f048_schema_contract.py`）。不搬 `features/v3.0.0/049-*`（已入 `reference/`）；`docs/constitution.md` C5 改动要搬。备选「按设计重写」——多 5～7 人天且失去 3000 行测试，否决。**何时重新考虑**：vibe 在移植后又对 `open_api/` 做了大改（合并时按文件对比即可）。

**A2：补 Alembic。** vibe 靠 `create_all(checkfirst=True)` 建 `api_credential` / `service_account`，beta1 面向存量客户升级，两表**必须有 revision**（模板 `v2_5_1_f012_user_token_version.py`；DDL 只建表建索引，不写数据，INV-26 同向）。`user.user_type` 的 revision 随提交带来，检查 `down_revision` 接到 beta1 当前 head（vibe 分叉后 beta1 可能新增了 revision → 改 `down_revision` 而非重排）。

**A3：端点接入沿用 vibe D3（标记 + router 级统一判定）。** 38 端点映射已在 `scopes.py` 写死并有 import-time 断言；beta1 上多出的 1 个 HTTP 端点（43 vs 42）落 spec 时重数并补进映射（同时补 PRD 附录 B.1 回写）。**标记签名扩展为**
`@open_api_scope(scope: str | None, *, modes=("S", "D"), session=False, allow_share_token=False, idempotent=False)`——`modes` 由 WS-C 消费、`session` 标 ⧗ 端点（End-User 头写分区键 + 缺省 WARN）、`idempotent` 由 WS-F 消费。WS-A 落标记时**一次把四个参数按附录 B.1 填好**，避免三个工作流各改一遍同一行。仅 S 的端点：`GET /filelib/download_statistic`、`POST /llm/workbench/asr`、`/tts`；`session=True`：`workflow/invoke`、两个 WS、`assistant/chat/completions`、日常模式会话三端点。

**A4：`resolve_operator` 在 WS-A 期保留（收紧：目标 `delete==0` ∧ 目标活跃租户 == 密钥租户，否则 403），WS-C 移除。** 这是 WS-A 与 WS-C 必须同版发布的原因。

**A5：其余全部沿用 vibe-049 D1 / D2 / D4 / D5 / D6 / D7 / D9 / D10 / D11 / D12**（主体形态、校验位置与缓存、6 端点真 404、资源归属人接缝、授权页反查、选人排除、权限位注册表与开关、错误码、审计 lockstep、配置移除），本文不重抄；实现者以 `reference/vibe-049-design.md` §3–§5 为准，差异只有 §2.2 列出的十条。

### 5.B 管理界面（platform）

**B1：组件原样移植，按设计规范核对视觉。** platform 仍以 `@/components/bs-ui` 为组件库（beta1 上 335 个文件在用、`@bisheng/ui` 零引用），vibe 8 个组件同样基于 `bs-ui`，**直接搬、不换组件**；移植后按 `src/frontend/packages/ui/docs/` 的设计规范（字体 / 色彩 / 圆角阴影 / 组件使用规则）核对一遍，视觉改动需设计师确认（root AGENTS.md §4 Ownership）。`react-query` 冻结（vibe 坑 24）仍成立，用 `useTable` / `useState+useEffect`。

**B2：一个菜单，四个 tab。** 系统管理 → 「服务账号」（列表 / 新建 / 详情三 tab：概览 · API 密钥 · 资源授权）；「个人访问令牌」作为**同级 tab**（不是服务账号的子 tab——PRD §4.7「两者不共用界面、不共用入口、互不可见」），内含：租户开关（部署级未开 → 置灰 + 说明「需运维在 config.yaml 开启 `open_api.pat_enabled` 并重启」）、默认有效期（天，默认 365）、台账表（持有人 / 掩码 / 创建 / 最后使用 / 有效期 / 权限位 / 管理员高亮标记）、单个吊销、按人批量吊销。单租户部署只显示租户级那一个开关（`appConfig.multiTenantEnabled` 已有）。

**B3：签发 / 编辑表单四组**（PRD §4.7.3）：基本（名称 / 过期）· 权限位（7 个开关 + toolkit 组仅 `openPlatformEnabled`）· 委托配置（勾 `delegate` 展开：范围选择器 = `DepartmentUsersSelect` 多选 + 部门树多选，两类混用；范围为空保存禁用；与 toolkit 三位互斥硬阻断，文案「配了委托的密钥不能用于本地开发，请另签一把」；风险提示「每次调用必须声明被代表用户，漏传即 400」）· 网络（IP 白名单 CIDR 多行、限流 rpm、日配额；留空 = 不限）。编辑与签发同一表单、同一校验。**委托配置在 WS-C 端点未就绪前隐藏**（按 `GET /scopes` 是否返回 `delegate` 位判断，不加前端开关）。

**B4：资源授权 tab 沿用 vibe D6**：`GET /{id}/grants` 反查 + 来源列（管理员授予 / 创建时自动回授 / 异常来源）+ `grants:mutate` 逐条反馈 + 「全部撤销」排除回授 + 顶部展示名下密钥与权限位并对「本页已授权但无密钥持对应位」的资源提示 + 名下存在 `delegate` 密钥时显著提示「委托生效时本页授权不参与判定」。

### 5.C 身份传递

**C1：身份头解析与模式分流放在管线槽位 ⑦，实现在 `identity_service.resolve_identity(principal, headers, endpoint_marker) -> ResolvedIdentity`。** 备选「每个端点自己解析」——违反 K13，否决。解析结果写进 `OpenApiPrincipal.mode / effective_user_id / on_behalf_of_user_id / end_user_id`（§6.1）。OBO 头值**只接受用户 ID**（vibe-050 决议-1）；End-User 头形式约束：≤128 字节、可打印 ASCII，超限 `26018`。**何时该重新考虑**：出现「同一把密钥必须在同一连接内切换被代表用户」的场景（WebSocket 上目前握手期定身份、连接期不可变）——那时需要逐消息准入，成本是每条消息一次五道检查。

**C2：委托范围 = 独立表 `api_credential_delegate_scope(id, tenant_id, credential_id, subject_type∈{user,department}, subject_id, create_time)`**，索引 `(credential_id, subject_type, subject_id)`。备选「存进 `api_credential` 的一个 JSON 列」——DM8 上 `JsonType` 落 CLOB、无法在 SQL 里按条目判命中（vibe K5），调用期判定就得把整列取回 Python 遍历；范围可达数百条部门时热路径退化。独立表让检查 4 是一次索引点查。**何时该重新考虑**：范围条目数在真实客户处始终 ≤ 5 且从不按部门（那时 JSON 列 + 缓存载荷内联更省一次查询）。`delegate` 位本身仍在 `api_credential.scopes` JSON 里（唯一开关）。编辑时去掉 `delegate` → 同事务删全部范围行（vibe-050 决议-5，不留「范围非空但未勾」的死配置）。保存 `user` 条目校验自然人（`26021` 同族，早报错）；**department 子树在调用期展开**：`UserDepartment` join `Department.path LIKE '{path}%'`（现有物化路径），一次索引查询判目标是否命中任一条目。

**C3：五道准入的实现顺序与取证**：① `'delegate' in scopes` → 否则 `26004`；② 取目标 `User` 行：不存在 / `delete!=0` / `user_type!='human'` / 活跃租户 != 密钥租户 → **同一个 `26005`，响应体与耗时形状一致**（四种情形走同一分支、同一序列化，不 early-return 差异化消息）；③ **超管 / 租户管理员判定复用权限运行时的谓词**（`_check_is_global_super` + `is_tenant_admin`，与 `resolve_permission_actor` 同源；默认租户下无租户管理员档，测试按租户分别设计）→ `26007`；④ 范围命中（C2）→ 否则 `26004`；⑤ `'D' in marker.modes` → 否则 `26006`。全部通过后**目标身份构造**：`init_login_user`-等价的 `UserPayload`（角色列表取全，`is_global_super` 必为 False——③ 已保证；`resolve_permission_actor` 会按目标算 `tenant_admin_tenant_ids`，同样为空）。PAT 携带 OBO → 在 ① 之前拦：`26004` + 文案「个人密钥不支持委托」（AC-P15，不静默忽略）。

**C4：模式 D 的会话与资源归属**：`effective_user` = 目标 → `MessageSession.user_id` = 目标（会话回到员工工作台，vibe-050 决议-8）；创建类端点 owner = 目标、**不回授服务账号**（决议-9）——在 vibe D5 接缝处按 `principal.mode == 'D'` 分支：`owner_user_id=effective_user`、`autogrant_user_id=None`。

**C5：逐调用审计 = 新表 `open_api_call_log` + 纯 ASGI 中间件（只挂 `/api/v2`）+ 进程内有界队列批量落库。** 备选：a) 复用 `audit_log` 表——它是操作审计（低频、有 UI 语义），逐调用是高频访问日志，混表会把审计页拖垮；b) 每请求同步 INSERT——DM8 写放大（vibe 坑 20 同形）；c) Celery——每请求一条消息进 Redis，开销比批量落库大。选 **c) 之外的批量**：中间件在响应 `send` 完成后把记录放进 `asyncio.Queue(maxsize=10000)`，lifespan 启动的 flusher 每 1s 或攒满 200 条批量 `INSERT`——**按 `tenant_id` 分组、每组 `set_current_tenant_id(tid)` 后插入**（同 `worker/tenant_reconcile/tasks.py` 的「枚举在 bypass 内、写入按行切租户」写法，不用 bypass 直写、C3 自动填充照常生效）；队列满 → 丢弃并计数（日志 `open_api.audit.dropped`），进程退出前 flush 一次。flusher 只需在 API 进程注册（只有它服务 `/api/v2`，C8「每个需要的进程角色都注册」满足）。**已知代价**：进程崩溃丢最多 1s 记录——审计不是计费，可接受；WS 建连一条（复用 `open_api.ws.connect`）、断连一条。字段见 §6.4。保留期 Beat 清理（默认 90 天，`open_api.call_log_retention_days`）。**何时该重新考虑**：合规要求「零丢失」（那时改为每请求同步 INSERT + DM8 分区表，接受写放大）；或调用量使单表月增 > 千万行（那时按月分表或转 ClickHouse 类存储，中间件与队列不变、只换 flusher 的落点）。**Principal 传递**：依赖把 principal 同时写 ContextVar 与 `conn.scope["open_api_principal"]`——ASGI 中间件在外层任务、读不到内层 ContextVar 的修改，只能读共享的 scope dict（坑 §8-4）。

**C6：`POST /filelib/retrieve` 补文件级过滤**：`_aretrieve_chunks_for_kb` 与 `_aretrieve_chunks_for_knowledge_base` 两个分支改为与 `_retrieve_and_filter`（`knowledge_space_chat_service.py:486`）同强度：先 `KnowledgeFileVisibilityService.build_index_prefilter(user, kb_ids)`（阈值 5000）下推向量库 / ES，再 `post_filter_visible_files` 兜底。执行身份 = `effective_user`（模式 S 服务账号 / 模式 D 目标 / PAT 持有人）。**铁律 3 专项**：过滤器抛异常必须向上抛成 503，不得被 `except: pass` 吞成全量——落地时对两分支加「异常 → `PermissionServiceUnavailableError`」并写反向测试（mock 过滤器抛错 → 断言 503 且 body 无 chunk）。文档知识库无文件级模型，按库级（PRD §4.10.8 边界）。

**C7：裸 `user_id` 收口**：`POST /filelib/retrieve`、`GET /filelib/`、`GET /filelib/file/list`、`POST /filelib/add_qa` 四处真实读写 + `GET /assistant/list`、`POST /filelib/add_relative_qa` 两处死参数——请求体 / 查询串出现 `user_id` → 400 `26019`「参数已移除，请改用 X-Bisheng-On-Behalf-Of」；`resolve_operator` 删除。用 pydantic `extra='forbid'` 拦不住查询参数，在端点体显式判。

**C8：分区键**：`MessageSession.external_user_id VARCHAR(128) NULL` + 索引；`ChatMessage.external_user_id` 冗余（照抄 `tenant_id` 双写）；`filter_session / afilter_session / filter_session_count` 加可选参数、本版无调用方传值（只写不读）。share-token 会话写 `share_link_id` 作分区值（vibe-049 D8 已知代价的后续项，本版顺手写入、不摘出列表）。

### 5.D 个人访问令牌

**D1：主体 = `subject_kind='natural_person'`，前缀 `bs-pat-`，同一张 `api_credential` 表。** 解析器：`aget_user(user_id)` → `delete==0 ∧ user_type=='human'` → `aget_active_user_tenant(user_id).tenant_id == credential.tenant_id`（离开租户即失效）→ **取角色 + `_check_is_global_super`（Redis `user:{id}:is_super` 缓存）写入凭据缓存载荷**（`roles`, `is_global_super`）；构造 `UserPayload(user_role=roles, is_global_super=…)` 让 `resolve_permission_actor` 得到正常的管理员短路；**但 `set_visible_tenant_ids` 恒为 `{leaf,1}`/`{1}`，不因超管返回 None**（K16 / 附录 E.6）。失败 → `26043`（与 `26002` 区分：持有人要知道「是账号停了」）。

**D2：一人一把、无名称。** `personal_token_service.obtain(user)`：若已有有效令牌 → 先 `revoke(reason='regenerated')` 再签；`delete(user)` → `revoke(reason='manual')`；两者都主动删缓存键。`scopes` 固定 `['knowledge:read']`；直调管理端点传其它位 → `26041`；传 `expires_at` 超过租户 TTL → `26042`（员工 UI 不出现该字段）。管理员持有人签发时响应带 `warn_admin_full_read=true`（前端二次确认「可读取本租户全部知识」），有效期取 `min(租户默认, open_api.pat_admin_ttl_days 默认 90)`。

**D3：两层开关。** 部署级 `Settings.open_api.pat_enabled: bool = False`（config.yaml，重启生效，三段式同 `open_platform`，经 `GET /api/v1/env.pat_deploy_enabled` 透给前端）；租户级新表 `open_api_tenant_setting(tenant_id PK, pat_enabled bool default false, pat_ttl_days int default 365, update_time)`——备选「复用 workstation 租户配置」：那套配置是工作台偏好、混入治理开关语义不清且要核实其是否真按租户存，否决。管线槽位 ④ 读两层（租户级走 Redis 缓存 60s + 写时主动失效，保证「关闭 5 秒内不可用」）。**关闭 = 停用不撤销**：不写 `revoked_at`，重开即恢复（AC-P1a）。开关按主体类型独立——服务账号密钥不受影响（硬规则 2）。**何时该重新考虑**：平台出现统一的「租户级治理配置」对象（多个 Feature 都要租户开关时）——那时把本表并入，字段语义不变。

**D4：级联失效 = 三个触发点 + 校验期兜底。** 触发点：① `/user/update` 走 `update_user_delete_hook` 置 `delete=1`（`user/api/user.py:726`）；② 用户删除路径（同文件 / `UserService`）；③ `user_tenant_sync_service.sync_user` 判定租户变更时。三处调既有 `revoke_all_by_subject('natural_person', user_id, reason)`（`subject_disabled` / `subject_deleted` / `subject_disabled`）+ `invalidate_subject_cache`。兜底：解析器每次 miss 重判（3s 缓存），5 秒上界成立。

**D5：员工自助端点（登录态，`/api/v1/me/api-token`）**：`GET`（状态：掩码 / 状态 / 有效期至 / 创建 / 最后使用；无令牌返回 `null`）· `POST`（获取 / 重新获取 → 唯一返回明文处）· `DELETE` · `GET /install-prompt`（按 `request.base_url` 生成三行提示词 + curl 示例；Base URL 取反向代理头 `X-Forwarded-Proto/Host` 优先）。**管理员端点（`/api/v1/personal-tokens`，`get_service_account_admin` 同门禁）**：`GET`（分页台账，只返元数据，含 `holder_is_admin` 标记）· `POST /{id}/revoke` · `POST /revoke-by-user/{user_id}` · `GET/PUT /settings`（租户开关 + TTL；部署级未开时 `PUT enabled=true` → `26040`）。

**D6：技能包 = 仓内目录 + 内存 zip。** `bisheng/open_api/skill_packs/bisheng-knowledge-search/{SKILL.md, meta.json, references/api.md, scripts/bs_request.py, SECURITY.md}`；`GET /api/v1/open-api/skills/bisheng-knowledge-search.zip`（匿名，路径加入 `TENANT_CHECK_EXEMPT_PATHS`；zip 内 `SKILL.md` 的 Base URL 与 `SECURITY.md` 的出站白名单在下发时按当前实例地址渲染，`mtime=0` 可复现）。备选「移植 vibe `dev_toolkit/`」——它是应用工场 CLI 的分发面、带 tarball 与版本清单，为一个 zip 搬整个模块不值，否决；**何时重新考虑**：beta1 后续合并 vibe 时把本端点并入 `dev_toolkit`。SKILL.md 要写清：先调 `GET /api/v2/filelib/` 拿知识空间清单再 `POST /filelib/retrieve`；凭据从 `BISHENG_API_KEY` 环境变量优先、回落 `~/.bisheng/credentials.json`；错误码 401/403/429 分层处理；触发词「知识库 / 检索 / 搜一下有没有」。

**D7：client 个人中心落点**：`layouts/UserPopMenu.tsx` 新增菜单项「API 令牌」→ `components/PersonalTokenDialog.tsx`（Recoil + shadcn；四件事：获取 / 状态 / 删除·重新获取 / 安装提示词 + curl 示例；明文一次性展示复用「必须勾选已保存」交互，**不搬 platform 的 `KeyRevealDialog`**（技术栈不同，行为对齐即可）；开关未开时菜单项隐藏——`GET /api/v1/env` 增 `pat_enabled`（部署 ∧ 租户）。`Nav/AccountSettings.tsx` 是死代码不用（附录 E.6）。

**D8：对客文档改名**：`docs/api/*.md` 与 platform `ApiAccess*.tsx` 中「服务账号模式」→「自身身份模式」，错误码表处置建议列同改（AC-P22）。

### 5.E 日常模式会话开放

**E1：契约形态 = 平台自有业务语义契约（不对标 OpenAI Responses / Chat Completions）。** 备选：a) Responses 子集——PRD D9 已述语义错配（模型侧契约承接应用侧能力）、兼容承诺被拒绝清单掏空、任务模式的 `ask_user` / MinIO 产物表达不了；b) Dify 风格 `/chat-messages`——形态合适但名字与语义借用同样是兑现不了的暗示（K20）。选 **自有命名**，形态借鉴 Dify 的「业务入参 + 事件流」结构。**何时重新考虑**：出现「某第三方生态工具必须直连本面且既有 `POST /api/v2/assistant/chat/completions` 无法替代」的确认客户。

**E2：三个端点（均 `chat:invoke`，S/D，`session=True`）**：

```
POST /api/v2/workbench/chat            发起一轮（流式 / 非流式）        idempotent=True（仅非流式）
GET  /api/v2/workbench/turns/{turn_id} 按标识取回单轮结果（不透明 id；不匹配 404）
POST /api/v2/workbench/files           上传会话附件（multipart；沿用工作台限制）
```

请求体（白名单式，契约外字段 400 指名）：

| 字段 | 类型 | 必填 | 映射到内部 |
|---|---|---|---|
| `query` | string | 是 | `APIChatCompletion.messages[-1].content` |
| `model` | string | 是 | 模型管理页原名精确匹配，跨服务商同名 → 400 要求限定名 |
| `session_id` | string | 否（多轮必填） | `MessageSession.chat_id`；首轮由平台返回 |
| `knowledge` | `[{id}]` | 否 | 挂载知识库；模式 S 传个人知识库 → 400 |
| `tools` | `[{type:"bisheng_tool", tool_key}]` | 否 | 其它 `type` → 400 指名（AC-34） |
| `attachments` | `[{file_id}]` | 否 | 只接受本面上传得到的 id |
| `instructions` | string | 否 | 叠加于平台系统提示词之上，不替换 |
| `stream` | bool | 否，默认 `false` | 传输形态 |
| `run_mode` | `"daily"` | 否，默认 `daily` | `"task"` / 其它 → 400 `26017` |
| `execution` | `"sync"` | 否，默认 `sync` | `"async"` / 其它 → 400 `26015` |

响应（非流式）：`{session_id, turn_id, answer, citations:[…], tool_calls:[{tool_key, input, output}], usage, finished_at}`。流式 SSE 事件类型（每事件 `{event, turn_id, session_id, data}`）：`turn.started` · `thinking.delta` · `answer.delta` · `tool.call` · `tool.result` · `citation` · `turn.completed`（终态，含聚合结果）| `turn.failed`（终态）。每轮**有且仅有一个终态**；非流式返回 = `turn.completed.data`。失败轮次不留存（vibe-058 决议-9）。

**E3：复用映射**：`POST /api/v1/workstation/chat/completions` 的 `stream_chat_completion`（`workstation/api/endpoints/chat.py:97`）→ 抽 `WorkstationChatService.run_daily_turn(login_user, DailyTurnInput) -> AsyncIterator[TurnEvent]`（把现有 SSE 文本流改为先产内部事件、再由两个适配器分别渲染工作台 SSE 与 V2 SSE——**不复制一条链路**）。**C1 / RULE-5 约束**：V2 端点文件 `open_endpoints/api/endpoints/workbench.py` 只能 import `bisheng.workstation.domain.services.*`，**禁止** import `bisheng.workstation.api.*`（API 层跨模块导入即 arch-guard VIOLATION）——这正是必须先抽 service 的原因，不是可选重构。备选「V2 端点内部 HTTP 转调 `/api/v1/workstation/chat/completions`」——多一跳、身份要伪造成 JWT、审计断链，否决。**何时该重新考虑**：工作台链路自身重构为事件驱动（那时 V2 适配器直接消费其事件总线）；入参清洗把 `clientTimestamp` 改可选（附录 E.3 陷阱）；`task_mode` 恒 False。附件上传复用 `workstation/api/endpoints/knowledge.py upload_file`。

**E4：归属**：`session_id` / `turn_id` / `file_id` 三处校验基准 = 会话归属主体（模式 S：服务账号 + `end_user_id` 分区键；模式 D：目标用户）；不匹配 / 跨租户 / 不存在一律 404 且形状一致（vibe-058 决议-3）。模式 S 未传 End-User 只 WARN。

### 5.F P2 运营能力

**F1：凭据表加三列**：`ip_allowlist JsonType(list[str] CIDR) NULL`、`rate_limit_rpm INT NULL`、`quota_daily_calls INT NULL`（NULL = 不限）。Alembic 加列。签发 / 编辑端点透传，编辑即时生效（缓存载荷含三列、主动失效）。

**F2：限流 = Redis 令牌桶 Lua，按 `credential_id`，fail-closed；日配额 = 独立计数器。** 备选：a) 固定窗口计数（`INCR` + `EXPIRE`）——实现最简，但窗口边界可双倍突发，对"每分钟 N 次"的合同语义不准；b) 滑动日志（ZSET）——精确但每请求 O(log n) 且键膨胀；c) **令牌桶 Lua**——一次 `EVAL` 原子取令牌、允许合理突发、键恒定大小。选 c。key `oapi:rl:{credential_id}`，容量 = rpm、速率 = rpm/60；Redis 异常 → `26030` 503（K18）。日配额：`oapi:quota:{credential_id}:{YYYYMMDD}` `INCR` + `EXPIREAT` 次日零点（租户时区取平台配置）；超限 → `26009` 429，响应头 `X-RateLimit-Limit / Remaining / Reset`。**不按外部标识计量**（PRD §4.3.4）。**两个槽位不同**（§3.1）：限流在 ③′（凭据解析成功即计，随后被 403 拒的请求也计入——防用错误请求探测）；日配额在 ⑧（只对通过全部校验、真正要执行的请求计数——配额是"用了多少"不是"打了多少"）。**何时该重新考虑**：出现按租户总量而非按密钥的合同需求（那时在 ⑧ 加一层租户级计数器，不动 ③′）；Redis 单点成为瓶颈（令牌桶键按 credential 分散，可分片，不需改算法）。

**F3：IP 白名单**：来源 IP 取值 = 若 `settings.open_api.trusted_proxies` 非空且直连 IP 在其中 → 取 `X-Forwarded-For` 最右一个不在 trusted 的地址；否则用直连 IP。`ipaddress.ip_address in ip_network` 逐条匹配；不在 → `26008`。列表为空 = 不限。

**F4：幂等 = `Idempotency-Key` 头 + Redis 响应快照。** 只对 `idempotent=True` 端点生效；key `oapi:idem:{credential_id}:{sha256(key)}`，值 `{fingerprint, status, body, created}`，TTL 24h；流程：`SET NX` 占位（`in_flight`）→ 执行 → 写快照；命中已完成 → 直接返回快照 + 头 `Idempotent-Replayed: true`；命中 `in_flight` → 409 `26011`；命中但请求体指纹（`sha256(method+path+body)`）不同 → 409 `26011`。实现为依赖 `Depends(idempotency_guard)` 挂在标记端点上（依赖需读 body：用 `await request.body()` 后 Starlette 会缓存，端点体再读不受影响）；快照只存响应体不存请求头。流式响应不支持幂等（`stream=true` 时忽略该头并在响应头声明 `Idempotent-Replayed: unsupported`）。备选「落库存快照」——幂等窗口只有 24h、快照是响应体副本不是业务真相，进 DB 只增加 DM8 写放大与清理任务，否决。**何时该重新考虑**：客户要求幂等窗口 > Redis 内存可承受（如 7 天）或要求幂等记录可审计——那时改为 DB 表 + Redis 只做在途锁。

### 5.G share-token 通道

**沿用 vibe-049 D8 全部**（`share_scope` 列 + 相对秒有效期 + `POST /api/v1/app-shares/{id}/revoke` / `GET /api/v1/app-shares` 登录态管理端点挂非豁免前缀 + 3 个匿名作用域端点 `GET /api/v1/share-link/{token}/{resource|chat/history}` / `POST …/chat/gen_title` + 两个 WS `?share_token=` + 3s watchdog + 执行主体 = 分享创建者 + 审计 `open_api.ws.connect`），client guest 页从 query 取 token、不再打任何 `/api/v2` HTTP；platform `ChatLink` URL 改 `${origin}${BASE_URL}/workspace/chat/{flow|assistant}/{id}?share_token=…`。beta1 上核实：`client/pages/standaloneChat/StandaloneChatPage.tsx` guest 分支仍是 `apiVersion='v2'`，`useChatHelpers.ts` 拼 WS URL 处即改动点。**增量**：会话写 `external_user_id = 'share:{share_link_id}'`（C8）。

---

## 6. 共享契约（所有工作流对齐的单一来源）

### 6.1 `OpenApiPrincipal`（`open_api/domain/context.py`，frozen pydantic）

```python
class OpenApiPrincipal(BaseModel, frozen=True):
    credential_id: int | None            # share_link 时 None
    subject_kind: Literal["service_account", "natural_person", "share_link"]
    subject_user_id: int                 # 密钥主体的 user_id（share_link = 分享创建者）
    resource_owner_user_id: int | None   # 仅 service_account
    share_link_id: int | None
    scopes: frozenset[str]
    tenant_id: int
    mode: Literal["S", "D"] = "S"        # [WS-C] 填；WS-A 期恒 S
    effective_user_id: int               # 执行身份：S = subject_user_id；D = on_behalf_of_user_id
    on_behalf_of_user_id: int | None = None
    end_user_id: str | None = None       # X-Bisheng-End-User 原值（形式校验后）
    def has_scope(self, code: str) -> bool: ...
```

写入点：`verify_open_api_access` 同时 `current_open_api_principal.set(p)` 与 `conn.scope["open_api_principal"] = p`。`UserPayload.open_api_principal` 指向同一对象；`UserPayload.user_id == effective_user_id`。**任何工作流不得自行构造第二个 principal**。

### 6.2 端点与 API 契约总表

| 面 | 端点 | 鉴权 | 归属 |
|---|---|---|---|
| 开放面 `/api/v2` | 既有 38 HTTP + 2 WS（附录 B.1） | Bearer；WS 另接受 `?share_token=` | A / G |
| | `GET /auth/whoami` | Bearer，`scope=None` | A |
| | `POST /workbench/chat` · `GET /workbench/turns/{id}` · `POST /workbench/files` | Bearer `chat:invoke`，S/D | E |
| 管理面 `/api/v1`（管理员） | `/service-accounts/**`（vibe §4.2 全表）+ `PATCH /{id}/keys/{key_id}` 增 `delegate_scope[] / ip_allowlist / rate_limit_rpm / quota_daily_calls` | JWT + `get_service_account_admin` | A / C / F |
| | `/personal-tokens`（台账）· `/personal-tokens/{id}/revoke` · `/personal-tokens/revoke-by-user/{uid}` · `/personal-tokens/settings` | 同上 | D |
| | `/app-shares`（列表 / 撤销） | JWT，创建者或管理员 | G |
| 员工面 `/api/v1` | `/me/api-token`（GET / POST / DELETE）· `/me/api-token/install-prompt` | JWT | D |
| 匿名 | `/open-api/skills/{pack}.zip` · `/share-link/{token}/{resource,chat/history,chat/gen_title}` | 无（豁免前缀） | D / G |
| 环境 | `GET /env` 增 `open_platform_enabled` / `pat_deploy_enabled` / `pat_enabled` | — | A / D |

请求头：`Authorization: Bearer <key>` · `X-Bisheng-On-Behalf-Of: <user_id>` · `X-Bisheng-End-User: <≤128 可打印>` · `Idempotency-Key: <≤255>`。响应头（P2）：`X-RateLimit-Limit / -Remaining / -Reset`、`Idempotent-Replayed`。

### 6.3 错误码分配（模块 260，落码时按 C5 回写 `docs/constitution.md`）

| 段 | 码 | 含义 | HTTP | 归属 |
|---|---|---|---|---|
| 开放面 | 26001 缺少/非法密钥 · 26002 无效/撤销/过期 · 26003 缺权限位（`data.required`）· 26004 未授予委托/不在范围（WS-A 期借作「身份传递未启用」）· 26012 服务账号禁止登录 | 401/401/403/403/403 | A |
| | 26005 委托目标无效（四情形无差异）· 26006 端点不支持代表模式 · 26007 目标为特权主体 · 26010 身份头冲突 · 26016 持 delegate 漏头 · **26018** End-User 形式非法 · **26019** 裸 `user_id` 已移除 | 403/403/403/400/400/400/400 | C |
| | 26008 IP 不在白名单 · 26009 超限流/配额 · 26011 幂等键冲突 | 403/429/409 | F |
| | 26015 异步未开放 · 26017 任务模式未开放 | 400/400 | E |
| | 26040 PAT 能力未开启 · 26041 权限位不在白名单 · 26042 有效期超上限 · 26043 持有人已停用/删除/离开租户 | 403/400/400/401 | D |
| 管理面 | 26020–26029（vibe D10：账号不存在 / 归属人无效 / 禁止操作 / 扩展位未部署 / 委托未启用 / 未知位 / 密钥不存在 / 账号停用 / 分享链接无效 / SA 不可作资源侧主体）· 26030 依赖不可用 · 26031 端点未登记 | 信封 / 503 / 500 | A / G |
| 预留 | 26013 / 26014 已废止不复用；26032–26039 留给管理面增量；26044–26049 留 PAT | | |

三语文案只落 `packages/locales/src/api_errors/*.json`，生成物跑脚本不手改。

### 6.4 数据契约

| 对象 | 字段 | 归属 |
|---|---|---|
| `api_credential`（vibe §4.2）+ 增列 | `ip_allowlist JSON NULL` · `rate_limit_rpm INT NULL` · `quota_daily_calls INT NULL`；`subject_kind` 取值增 `natural_person`；`revoke_reason` 取值增 `regenerated` | A / F / D |
| `api_credential_delegate_scope` | `id · tenant_id · credential_id · subject_type VARCHAR(16) · subject_id INT · create_time`；idx `(credential_id, subject_type, subject_id)` | C |
| `open_api_call_log` | `id · tenant_id · credential_id NULL · subject_kind · subject_user_id · mode CHAR→VARCHAR(1) · on_behalf_of_user_id NULL · end_user_id VARCHAR(128) NULL · share_link_id NULL · method · path VARCHAR(255) · scope VARCHAR(32) NULL · http_status · error_code NULL · client_ip VARCHAR(45) · latency_ms · create_time`；idx `(tenant_id, create_time)`、`(credential_id, create_time)`、`(on_behalf_of_user_id, create_time)` | C |
| `open_api_tenant_setting` | `tenant_id PK · pat_enabled BOOL default 0 · pat_ttl_days INT default 365 · update_time` | D |
| `message_session.external_user_id` / `chat_message.external_user_id` | `VARCHAR(128) NULL`，索引 | C |
| `share_link.share_scope` | `VARCHAR(16) server_default 'session'` | G |
| Settings（config.yaml） | `open_platform.enabled`(F) · `open_api.credential_cache_ttl_seconds`(3) · `open_api.service_account_idle_days`(90) · `open_api.pat_enabled`(F) · `open_api.pat_admin_ttl_days`(90) · `open_api.call_log_retention_days`(90) · `open_api.trusted_proxies`([]) | A / D / C / F |
| Redis key | `oapi:cred:{sha256}` · `oapi:cred:lastused:{id}` · `oapi:tenant:{tid}:pat` · `oapi:rl:{cid}` · `oapi:quota:{cid}:{ymd}` · `oapi:idem:{cid}:{sha256}` | 各自 |
| 审计 action（`audit_log`） | `open_api.service_account.*` · `open_api.api_key.*`（增 `regenerate`）· `open_api.grant.*` · `open_api.share_link.*` · `open_api.ws.connect` · `open_api.pat.{obtain,regenerate,delete,admin_revoke,setting_update}` | A / D / G |

### 6.5 我依赖别人的（Incoming）与风险点

底座部分的依赖清单见 `reference/vibe-049-design.md` §6.2（`user` / `user_tenant` / F048 runtime / `share_link` / Redis / MySQL·DM8 / `AuditLogDao` / Settings / FastAPI·Starlette 版本 / platform 组件 / client guest 页），在 beta1 上逐条仍成立。以下是本 Feature **新增**的依赖：

| 依赖 | 形式 | 谁用 | 风险点（什么变化会破坏我） |
|---|---|---|---|
| `permission/application/identity.py resolve_permission_actor` + `_check_is_global_super`（`utils/http_middleware.py`）+ `is_tenant_admin` | 内部 Python API（系统级放行谓词） | C 检查 3、D 管理员短路 | 谓词换源（如超管改从新表判）而准入检查 3 没跟 → 窄权限密钥换到管理员无界权限（K15，最重单点）；用例矩阵按租户分别设计 |
| `UserDepartment` + `Department.path` 物化路径 | ORM | C 检查 4 部门子树 | 路径分隔符 / 前缀规则变更 → `LIKE '{path}%'` 命中错；部门树重建期间路径暂不一致 |
| `KnowledgeFileVisibilityService.build_index_prefilter / post_filter_visible_files`、`_retrieve_and_filter` | 内部 Python API | C-⑥ 文件级过滤、D（AC-P7） | 阈值 5000 语义变 / 返回形状变 → 过滤退化为资源级而无报错；铁律 3 反向测试是唯一防线 |
| `MessageSessionDao.filter_session / afilter_session / filter_session_count`、`MessageSession` / `ChatMessage` 模型 | ORM + DAO | C-⑧ 分区键、E 归属校验 | 会话模块重构列名或列举路径 → 分区键写了没人读、归属校验漏 |
| `workstation/domain/services/chat_service.py`（`stream_chat_completion` → 抽 `run_daily_turn`）、`APIChatCompletion` schema、`upload_file` | 内部 Python API（**本 Feature 主动重构它**） | E | 工作台日常模式是活跃功能，抽 service 会动它的 SSE 渲染——**工作台前端零改动**是硬约束，需回归工作台聊天；`clientTimestamp` 必填死字段（坑 11） |
| `user/api/user.py update_user_delete_hook`、用户删除路径、`user_tenant_sync_service.sync_user` | 触发点（本 Feature 在其中加调用） | D 级联失效 | 新增第 4 条「用户失效」路径（如批量导入覆盖）而没加触发 → 令牌残活到校验期兜底（≤3s 缓存 + 下次 miss），5 秒上界仍成立但审计少一条 |
| `GET /api/v1/env`（`api/v1/endpoints.py get_env`）与 platform `appConfig` / client env 读取 | 配置三段式 | A / D 前端显隐 | 新增字段忘了透传 → 前端把开关当 `false`（安全方向） |
| `TENANT_CHECK_EXEMPT_PATHS`（`utils/http_middleware.py`） | 常量（本 Feature 加 2 个前缀） | D 技能包、G 作用域端点 | 前缀是 `startswith` 且命中即整链 bypass（坑 14）——登录态端点绝不可放在这些前缀下 |
| Redis Lua `EVAL`（`redis_manager` 异步连接） | 基础设施 | F 限流 / 幂等 | Redis Cluster 下多 key 脚本要同 slot（本设计每脚本单 key，安全）；Redis 不可用 = 开放面整体 503（K18 刻意） |
| `Department.path`、`Department` 根部门唯一性（`DepartmentRootExistsError`） | 业务不变量 | C「填根部门 = 全员」 | 多根部门出现 → 「根 = 全员」不再成立，委托范围要多填 |
| `docs/api/*.md`、platform `ApiAccess*.tsx` | 文档 | D-⑧ 改名 | 别的 Feature 又写回「服务账号模式」——CI 无法拦，靠 review |

---

## 7. 数据模型变更总表（Alembic，按 WS）

| revision（命名） | DDL | WS |
|---|---|---|
| `v3_0_0_f049_user_user_type`（随 cherry-pick 带来，改 `down_revision` 接 beta1 head；**文件名与 revision id 保留 vibe 原样**——日后合并 vibe 时同一 revision 自动去重，改名反而会让两边各加一次同名列） | `user.user_type` + idx | A |
| `v3_0_0b1_f053_api_credential_tables` | 建 `api_credential`、`service_account`（vibe 模型原样） | A |
| `v3_0_0b1_f053_delegate_scope_and_session_partition` | 建 `api_credential_delegate_scope`；`message_session` / `chat_message` 加 `external_user_id` + idx | C |
| `v3_0_0b1_f053_open_api_call_log` | 建 `open_api_call_log` + 3 索引 | C |
| `v3_0_0b1_f053_pat_tenant_setting` | 建 `open_api_tenant_setting` | D |
| `v3_0_0b1_f053_credential_p2_columns` | `api_credential` 加 `ip_allowlist / rate_limit_rpm / quota_daily_calls` | F |
| `v3_0_0b1_f053_share_link_scope` | `share_link.share_scope` | G |

规则：只 DDL、不写数据（INV-26 同向）；`VARCHAR` 不用 `CHAR`；JSON 列用 `JsonType`；每个 revision 独立可回滚；新表模块路径全部登记 `_TENANT_AWARE_MODEL_MODULES`（`bisheng.open_api.domain.models` 一次登记覆盖全部）。多人并行时 **revision 链由集成分支维护者串**（各 WS 先用 `down_revision = None` 占位，合入时改）。

---

## 8. 已知坑 / 反直觉事实（新增；vibe-049 坑 1–27 全部沿用）

| # | 事实 | 不知道会怎样 | 处理 |
|---|---|---|---|
| 1 | vibe 049 spec / design 写着「个人访问令牌整条否决、全平台只有 `bs-sak-`」 | 接手的人把 PAT 当成漏网旧方案再删一遍 | `reference/README.md` 与 §2.2-1 显式标注；PRD §7.6 记录了两次裁定的关系 |
| 2 | vibe 与 beta1 的 **F049–F052 编号撞车**（vibe 指开放 API 系列，beta1 指知识空间读优化等） | 文档互相引用错对象 | 本 Feature 编号 F053；引用 vibe 文档一律加 `vibe-` 前缀 |
| 3 | 三扩展位代码随移植进入 beta1，但三面不存在 | 有人在 beta1 上把 `open_platform.enabled` 打开 → 表单出现三位、签出的密钥没有任何端点可打 | 默认关；`docs/architecture` 加一句说明；不删（§2.2-2） |
| 4 | **ASGI 中间件读不到依赖里 set 的 ContextVar**（Starlette 把 app 跑在子任务，ContextVar 修改不回传） | 审计中间件拿到的 principal 永远是 None | 依赖同时写 `conn.scope["open_api_principal"]`（§5.C.5） |
| 5 | `_compute_visible_tenant_ids` 对 `is_global_super` 返回 `None`（整体关闭租户过滤） | 超管的 PAT 一把密钥横跨全平台租户 | 校验器内的副本对任何主体都按密钥租户算（K16 / 附录 E.6） |
| 6 | 默认租户下**没有「租户管理员」这一档**（身份解析只在 `tenant_id != DEFAULT` 时查） | 在默认租户构造「租户管理员目标」期待 `26007` 的测试永远失败 | 准入检查 3 的测试按租户分别设计（PRD 附录 E.5） |
| 7 | `department` 委托范围在**调用期**才展开；服务账号可能被组织侧兜底进「临时访客」部门（根之下） | 保存期校验过了、调用期一把密钥代表了另一个服务账号 | 检查 2 在调用期判 `user_type=='human'`，与范围类型无关（PRD §7.3） |
| 8 | 检索路径有两条强度不同：`/filelib/retrieve` 只做资源级校验；`filelib.py` 注释宣称「已有 per-user 过滤」**与实现不符** | 以为文件级过滤已做 → 模式 D / PAT 返回真超集（文件名 + 正文双泄露） | §5.C.6；权限关系名统一 `visible`（无 `view_file` / `view_space`） |
| 9 | `MessageSession` 没有任何可承载外部标识的列；`group_ids` 是用户组语义不可挪用 | 把 End-User 写进 `group_ids` 或只写 `ChatMessage` → 列表接口救不了 | 新列 `external_user_id`，落 `MessageSession` 且冗余到 `ChatMessage`（附录 E.3） |
| 10 | 内部 `task_mode` 分流的两个分支**都是同步 SSE**，任务模式真正的异步在后续 start-execute + WS 段 | 把「运行模式」和「同步/异步」做成一个开关 | `run_mode` 与 `execution` 两个字段各自校验（D11） |
| 11 | `clientTimestamp` 是内部入参的**必填死字段** | 直接复用内部 schema → V2 调用 422 | 适配层补默认值或改可选（附录 E.3） |
| 12 | 部门并发槽位那条 Redis Lua 原语在 Redis 故障时 **fail-open** | 照抄做限流 → Redis 一抖限流全失效 | 新写 Lua，异常 → 503（K18） |
| 13 | FastAPI 依赖里 `await request.body()` 后 Starlette 缓存 body，端点体可再读；但**流式请求 / multipart** 不适用 | 幂等依赖挂到上传端点 → 大文件全进内存 | 幂等只挂三个 JSON 端点，`stream=true` 忽略（§5.F.4） |
| 14 | `TENANT_CHECK_EXEMPT_PATHS` 是 `startswith` 前缀且命中即整链 bypass + 跳过 token_version | 把登录态管理端点放 `/share-link*` 或 `/open-api*` 前缀下 → 跨租户可见 | 匿名端点前缀 `/api/v1/open-api/skills`、`/api/v1/share-link/{token}`；登录态端点用 `/personal-tokens`、`/app-shares`、`/me/api-token`（vibe 坑 26） |
| 15 | beta1 上 `/api/v2` 实际 **43** 个 HTTP 端点（PRD 与 vibe 映射按 42 写） | `scopes.py` import-time 断言失败 / 完整性测试报未登记端点 | WS-A 打标时重数、补映射、回写 PRD 附录 B.1 |
| 16 | 平台 `handle_http_exception` 把一切压成 HTTP 200 + 信封 | v2 面 401/403/429/409/503 全部失真 | vibe D2 专属 handler；**新错误码必须继承 `OpenApiAuthError` 才带真 HTTP 状态**（WS-C/D/E/F 都要注意） |

---

## 9. 测试策略与 PRD 验收映射

**分层**：单元（`test/open_api/`，无外部依赖）· 集成（pytest + httpx，连 test 中间件 MySQL / Redis / OpenFGA，`asyncio_mode=auto`，断言 v2 面**真 HTTP 状态**、管理面**信封码**）· E2E（`/e2e-test`，页面手动清单）· DM8（105 回归：建 ≥2 个服务账号、PAT 一人一把重签、call_log 批量写）。

| PRD AC | WS | 关键用例 |
|---|---|---|
| AC-1～5, 21, 22, 40 | A / B | 无头 401 无回落；明文一次；撤销 ≤5s；缺位 403 指名；跨租户列表空；编辑不轮换 |
| AC-14～17, 42～47 | A | 登录矩阵 10 入口 26012；选人 8 处不见 SA；对账不改写；配额不计；归属人三路径；回授可撤且不进「全部撤销」 |
| AC-18～20, 32, 34～36, 50 | A / E / G | WS 握手拒绝优雅关闭；未上线 13010；stop 归属 403；模式 D 会话回工作台；未知工具 400；异步 26015；任务模式 26017 |
| AC-6～13, 23, 26, 37, 38, 41, 48, 49 | C | 五道准入逐条 + 26005 四情形形状一致 + 26007；范围空一律拒；漏头 26016 无业务数据；两头 26010；End-User 不改权限；模式 D 集合相等；FGA 不可用 503 无结果；审计双归属；裸 user_id 26019；delegate ⊗ 扩展位 |
| AC-24, 25 | F | 限流 429 + 头；同键只执行一次、异体 409；Redis 断 → 503 |
| AC-27 | A | 升级前后「默认操作员」用户零变化（快照对比） |
| AC-P1～P22 | D / B / C | 两层开关 5s 停用可逆；无有效期选项；只 knowledge:read；集合相等（正例）+ 无权文件不出现（反例）；三触发点级联；一人一把重签旧的失效；台账无明文；审计 actor/subject；PAT+OBO 拒；跨租户空；管理员短路 + 不跨租户；安装提示词带实例地址；zip 可解包；端到端装包→配密钥→提问 |
| vibe-049 AC-55～58（share-token） | G | 坏 token 拒；资源不符拒；撤销 / 过期 ≤5s（watchdog）；guest 页零 v2 HTTP |

**手动验证一遍**（以租户管理员账号登录 platform，非 `admin`，避免超管短路掩盖问题；`$BASE` = 实例地址）：

```bash
# M1 · 底座：建号 → 签发 → whoami
# platform：系统管理 → 服务账号 → 新建（归属人 = 自己）→ 直达签发 → 勾 knowledge:read → 复制明文 → 勾「我已保存」
curl -s -H "Authorization: Bearer $SAK" $BASE/api/v2/auth/whoami            # 200，scopes 含 knowledge:read
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/v2/auth/whoami           # 401（真 HTTP 状态，非 200 信封）
curl -s -H "Authorization: Bearer $SAK" $BASE/api/v2/assistant/list         # 403 26003，data.required=assistant:read
curl -s -H "Authorization: Bearer $SAK" $BASE/api/v2/chat/history           # 404（6 端点不暴露）
# platform 撤销该密钥 → 3 秒内再 curl whoami → 401 26002

# M2 · 身份传递
curl -s -H "Authorization: Bearer $SAK" -H "X-Bisheng-On-Behalf-Of: 1" $BASE/api/v2/filelib/     # 403 26004（未授予 delegate）
# platform 编辑密钥：勾 delegate + 范围=销售部；再签一把不带 delegate 的 $SAK2
curl -s -H "Authorization: Bearer $SAK" $BASE/api/v2/filelib/                                   # 400 26016（持 delegate 漏头）
curl -s -H "Authorization: Bearer $SAK" -H "X-Bisheng-On-Behalf-Of: <销售部张三 id>" \
     -X POST $BASE/api/v2/filelib/retrieve -d '{"query":"合同","knowledge_id":[...]}'          # 200，结果 = 张三在工作台检索所得
curl -s -H "Authorization: Bearer $SAK" -H "X-Bisheng-On-Behalf-Of: <admin id>" $BASE/api/v2/filelib/   # 403 26007
curl -s -H "Authorization: Bearer $SAK2" -H "X-Bisheng-End-User: crm-88" -X POST $BASE/api/v2/workflow/invoke ...  # 200，会话分区键写入
# 审计：SELECT * FROM open_api_call_log ORDER BY id DESC LIMIT 5 → 上述调用各一行，模式 D 行 on_behalf_of_user_id=张三

# M3 · 个人令牌（先在 config.yaml 开 open_api.pat_enabled，再在 platform「个人访问令牌」tab 开租户开关）
# client：头像菜单 → API 令牌 → 获取 → 复制 $PAT 与安装提示词
curl -s -H "Authorization: Bearer $PAT" $BASE/api/v2/auth/whoami                                 # 200，subject_kind=natural_person
curl -s -H "Authorization: Bearer $PAT" -X POST $BASE/api/v2/filelib/retrieve -d '{...}'          # 200，与本人工作台检索集合相等
curl -s -H "Authorization: Bearer $PAT" -H "X-Bisheng-On-Behalf-Of: 1" $BASE/api/v2/filelib/     # 403 26004「个人密钥不支持委托」
curl -s -o pack.zip $BASE/api/v1/open-api/skills/bisheng-knowledge-search.zip && unzip -l pack.zip   # 含 SKILL.md，Base URL = $BASE
# platform 关租户开关 → 3 秒内 curl whoami → 403 26040；重开 → 恢复；platform 禁用该用户 → 401 26043
# 把安装提示词贴给 Claude Code / openclaw → 提问「知识库里有没有 X」→ 结果与工作台一致（AC-P21）

# M4 · 会话与 P2
curl -N -H "Authorization: Bearer $SAK2" -X POST $BASE/api/v2/workbench/chat \
     -d '{"query":"你好","model":"<模型名>","stream":true}'                                      # SSE：turn.started … turn.completed
curl -s -H "Authorization: Bearer $SAK2" -X POST $BASE/api/v2/workbench/chat -d '{"query":"x","model":"m","execution":"async"}'   # 400 26015
for i in $(seq 1 70); do curl -s -o /dev/null -w '%{http_code} ' -H "Authorization: Bearer $SAK2" $BASE/api/v2/auth/whoami; done  # rpm=60 时第 61 起 429
curl -s -H "Authorization: Bearer $SAK2" -H "Idempotency-Key: k1" -X POST $BASE/api/v2/workflow/invoke -d '{...}'   # 两次 → 第二次头 Idempotent-Replayed: true
```

**可观测**：结构化日志 `open_api.call`（WS-A 期）→ 表化后保留日志行作为 Redis / DB 故障时的兜底；`open_api.auth.reject{code}` 计数；`open_api.audit.dropped`；`open_api.ratelimit.hit`；watchdog 断连原因。

---

## 10. 发布与升级

1. **部署顺序**（vibe 坑 22）：先发代码 → 再在 `config.yaml` 加 `open_platform:` / `open_api:` 顶层键 → 重启。未知顶层键会拒启。
2. **Alembic**：§7 七个 revision 按 WS 合入顺序串链；升级前备份 `share_link`、`message_session`。
3. **发布说明四项**（PRD §4.9，WS-A 交付）：升级后管理员三步；接入空窗；6 个不暴露端点清单；`download_statistic` 入参 `file_path → file_name`、裸 `user_id` 移除、存量裸分享链接失效。加：技能包与 PAT 的开启方式（默认关）。
4. **对客文档**：`docs/api/*.md` 删「网络层负责访问控制」「建议配置超级管理员」；身份模式改名「自身身份模式 / 代表他人模式」；错误码表 260 段；secret scanning 前缀 `bs-sak-` 与 `bs-pat-` 两条规则。
5. **最小可发版集** = M2（A + C + G）；B 缺失时管理员可用 API 建号发钥（不推荐对外）。

---

## 11. 后续 / 不做

- 任务模式（灵思）与异步执行：四项前置（异步作业语义、可重放事件流、后端统一编排、并发准入）完成后点亮，**不得推翻** §5.E 契约——`run_mode: "task"` 与 `execution: "async"` 两个字段就是留位；`turn.paused`（`ask_user`）与产物下载入口作为未来事件类型预留名字。
- 会话列表 / 历史 / 反馈 / 回填端点：不做、不留占位（D12）。
- 密钥级资源白名单、OAuth 授权服务器、Webhook 回调鉴权、企业网关签发令牌（D6 待定）：不做。
- share-token 会话从分享创建者列表摘出：分区键已写（`share:{id}`），列表过滤随后续会话功能一并做。
- 与 `3.0-vibe` 合并：本文 §2.2 的十条差异是合并时的对照清单；`open_api/` 模块结构与 vibe 保持同构就是为了这一步。

---

## 修订历史

| 日期 | 改动 | 触发 |
|---|---|---|
| 2026-08-31 | 初版：全量范围（P0+P1+P2）、7 工作流分工、共享契约、错误码分配、数据模型总表、16 条新增坑 | 用户裁定「所有需求一起设计、先出设计、多人分工」 |
| 2026-08-31 | `/sdd-review design` 自查修订 9 处：限流槽位前移到凭据解析后（原与 spec AC-F1「被拒请求计入限流」矛盾）、日配额留在执行前；补 §3.3 模块「做什么 / 不做什么」表；补 §6.5 新增依赖与风险点；补 §9 手动验证命令；C1 / C2 / C5 / D3 / F2 / F4 补备选与「何时该重新考虑」；E3 写明 RULE-5 约束；C5 flusher 改按租户切上下文写入（C3）；Alembic 保留 vibe revision id 的理由 | 评审 24 项清单 |
