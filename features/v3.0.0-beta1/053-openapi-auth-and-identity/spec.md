# Feature: 开放 API 鉴权与身份传递（F053，全量：P0 底座 · P1 身份传递 / 个人访问令牌 / 日常模式会话 · P2 运营能力）

> **本文档定位 — 范围裁定 + PRD 之外的补充 AC**
>
> 需求正文与验收标准的唯一真相是上游 PRD（`docs/product/3.0 开放 API 鉴权与身份传递 PRD.md` v2.4）：§4 需求、§5 验收（AC-1～50、AC-P1～P22）、§6 非目标、§7 决策记录。本 spec **不复述 PRD**，只做三件事：① 登记本版本对 PRD 范围的裁定；② 登记 PRD 未单列 AC 但本次必须交付的补充验收；③ 指向 design。
> How 一律在 [design.md](./design.md)。

**关联 PRD**: v2.4 全文（R1–R10，P0 / P1 / P2）
**参考**: [reference/](./reference/README.md)（vibe 049 spec 65 条 AC、050 spec 12 条决议、058 spec 14 条决议——**其 AC 编号与本文无关**，本文引用时加 `vibe-` 前缀）
**优先级**: P0（底座 + 端点接入）/ P1（身份传递、PAT、日常模式会话）/ P2（运营能力）
**所属版本**: v3.0.0-beta1 · **Discovery**: [../000-openapi-auth-discovery/discovery.md](../000-openapi-auth-discovery/discovery.md)
**依赖**: F048（权限运行时、`authorize_created`、`grants:mutate`、主体校验）· 既有 `share_link` / `workstation` / `knowledge` 模块 · 无本版本其他 Feature 依赖
**同步记录**: 2026-08-31 初稿（用户裁定：全量一起设计、按工作流分工；范围裁定见 §1）

---

## 1. 范围裁定（2026-08-31，★ 待用户确认）

| # | 裁定 | 依据 |
|---|---|---|
| S1 | **PRD R1–R10 全部纳入本 Feature**，含 P2（限流 / 配额 / IP 白名单 / 幂等）与 §4.6.3 日常模式会话开放；不拆成多个 Feature，按 7 个工作流分工（design §4） | 用户 2026-08-31 |
| S2 | **代码底座从 `3.0-vibe` 移植**（vibe F049 Wave 1–2 的 5 个提交），需求口径以 PRD v2.4 为准；vibe 文档中已被 PRD 推翻的结论不采纳（design §2.2） | 用户 2026-08-31 |
| S3 | **应用工场三扩展位（`model:invoke` / `identity:read` / `app:manage`）代码随底座移植但不建三面**：`open_platform.enabled` 默认关、表单不出现、签发被拒 | beta1 无应用工场；PRD §4.2.4「标准版不出现」 |
| S4 | **share-token 通道随本 Feature 交付**（PRD §4.6.1「浏览器直连：票据换取」的落地形态，vibe-049 D8）——否则锁 v2 WS 即打断两个免登录分享页 | design §5.G |
| S5 | **底座（WS-A）与身份传递（WS-C）同版发布**；其余工作流可后续合入 | PRD §4.9 裸 `user_id` 不留过渡期 |
| S6 | 任务模式（灵思）、异步执行、会话列表 / 历史 / 反馈 / 回填、第二套并行契约、OAuth、Webhook 回调鉴权、密钥级资源白名单、PAT 的非 `knowledge:read` 位：**不做**（PRD §6 原样） | PRD §6 |
| S7 | Feature 目录 `features/v3.0.0-beta1/053-openapi-auth-and-identity/`；release-contract 登记 6 个领域对象 + INV-29～34 + 错误码 260 | discovery §4-D |

---

## 2. 验收标准

### 2.1 PRD 验收（主体）

PRD §五 **AC-1～AC-50**（AC-33 已废止）与 **AC-P1～AC-P22** 全部适用，逐条与工作流的映射见 design §9。以下为 PRD 对本版本口径的两处补充：

- **AC-S1** — THE SYSTEM SHALL 在 beta1 上把 `/api/v2` 全部 **43 个 HTTP + 2 个 WebSocket** 端点纳入同一条凭据校验路径（PRD 附录 B.1 按 42 写，落地时重数、补映射并回写 PRD）；6 个 `/chat/*` 端点不暴露（真 404）。
- **AC-S2** — WHERE `open_platform.enabled=false`（beta1 默认）, THE SYSTEM SHALL 不在权限位清单与签发 / 编辑表单中展示三扩展位，且以三位入参的签发 / 编辑请求被拒绝（`26023`）。

### 2.2 补充 AC · share-token 通道（沿用 vibe-049 AC-55～58，口径按 design D8）

- **AC-G1** — WHEN 免登录分享页以有效 `share_token` 连接两个 WebSocket 端点, THE SYSTEM SHALL 以**分享创建者**为执行主体、以分享所属租户为租户上下文，且只放行 `share_scope='app'` 且 `resource_id` 等于路径资源 id 的分享；资源不符、`session` 级分享、创建者已禁用 / 删除、租户不活跃一律拒绝握手并优雅关闭。
- **AC-G2** — WHEN 分享被撤销或到期, THE SYSTEM SHALL 使新建连接立即被拒、已建立连接在 5 秒内断开；撤销为写入既有 `status=INACTIVE`（该枚举从此有写入端点）；`expire_time` 语义为自创建起的相对秒数，应用级分享必填 > 0。
- **AC-G3** — THE SYSTEM SHALL 使免登录分享页**不再调用任何 `/api/v2` HTTP 端点**；其信息 / 历史 / 标题读取经 `/api/v1/share-link/{token}/*` 匿名作用域端点，只放行该分享指向的资源及其 flow 下的会话。
- **AC-G4** — THE SYSTEM SHALL 使 share-token 通道不承载任何身份传递头（携带即拒），且 share-token 会话写入分区键 `share:{share_link_id}`。
- **AC-G5** — 撤销 / 列表管理端点 SHALL 挂在**非租户豁免前缀**（`/api/v1/app-shares`）下，受登录态、token_version 与租户过滤约束；直接 POST 撤销他人分享（非创建者且非管理员）→ 403。

### 2.3 补充 AC · 身份传递细则（PRD 未单列）

- **AC-C1** — `X-Bisheng-On-Behalf-Of` 只接受用户 ID；`X-Bisheng-End-User` ≤ 128 字节且为可打印 ASCII，否则 400（`26018`）；无会话语义的端点收到 End-User 头只留审计、不报错。
- **AC-C2** — 编辑密钥去掉 `delegate` 位时委托范围一并清除；不存在「范围非空但未勾 `delegate`」的持久化状态。
- **AC-C3** — 携带裸 `user_id` 参数的 6 个端点返回 400（`26019`），错误信息指向 `X-Bisheng-On-Behalf-Of`。
- **AC-C4** — 模式 D 下创建的资源**不回授**服务账号；模式 S 下仍按定义 6 回授。
- **AC-C5** — 逐调用审计记录含：时间、凭据 id、主体种类与 user_id、身份模式、被代表用户、外部标识、方法 / 路径 / 权限位、HTTP 状态与错误码、来源 IP、耗时；被拒调用同样记录；记录保留期可配置（默认 90 天）。

### 2.4 补充 AC · 个人访问令牌细则

- **AC-D1** — 管理员持有人签发时响应携带警示标记、前端二次确认；其有效期取 `min(租户默认, 部署级 pat_admin_ttl_days)`。
- **AC-D2** — 租户级开关与默认有效期变更 5 秒内对校验生效；关闭期间令牌行不写撤销位。
- **AC-D3** — 「重新获取」使旧令牌以撤销原因 `regenerated` 失效，与手动删除（`manual`）可区分。
- **AC-D4** — 技能包 zip 内 `SKILL.md` 的 Base URL 与 `SECURITY.md` 的出站域名白名单按当前实例地址在下发时渲染，仓库内不含任何实例地址。

### 2.5 补充 AC · 日常模式会话（形态按 design §5.E）

- **AC-E1** — 请求体白名单式接受；契约外字段、未知工具 `type`、`run_mode≠daily`、`execution≠sync` 分别返回 400 并指名出错项（后两者用 `26017` / `26015`），**绝不静默降级**。
- **AC-E2** — 流式返回每轮有且仅有一个终态事件（`turn.completed` / `turn.failed`）；非流式返回内容与流式聚合结果一致；失败轮次不留存。
- **AC-E3** — `session_id` / `turn_id` / `file_id` 的归属校验基准 = 会话归属主体（模式 S：服务账号 + 外部标识分区键；模式 D：被代表用户）；不匹配 / 跨租户 / 不存在一律 404 且响应形状一致。
- **AC-E4** — 模式 S 下挂载个人知识库 → 400 指名（服务账号无个人知识库）。

### 2.6 补充 AC · P2 运营能力

- **AC-F1** — 限流与日配额按**凭据**计量，不按外部标识；超限 429（`26009`）并携带 `X-RateLimit-Limit / -Remaining / -Reset`。限流在凭据解析成功后立即计（持有效凭据但随后被 403 拒绝的请求也计入）；日配额只对通过全部校验、真正执行的请求计数；无有效凭据（401）的请求没有计量维度、两者都不计。
- **AC-F2** — Redis 不可用时限流 / 配额 / 幂等一律拒绝（503 `26030`），不放行。
- **AC-F3** — `Idempotency-Key` 只对声明幂等的端点生效：同键同体 24h 内返回首次响应并带 `Idempotent-Replayed: true`；同键在途或同键异体 → 409（`26011`）；流式请求忽略该头并在响应头声明不支持。
- **AC-F4** — IP 白名单为 CIDR 列表；来源 IP 在配置了可信代理时取 `X-Forwarded-For` 最右侧非可信地址，否则取直连地址；不在名单 → 403（`26008`）。

---

## 3. 边界情况

- 底座与身份传递之间的过渡形态（WS-A 已合、WS-C 未合）**只存在于开发分支**：任何身份头一律 403 `26004`，`resolve_operator` 保留但收紧；不对外发版。
- 三扩展位在 beta1 上「注册表有、界面无、签发拒」——不是 bug。
- 超管的 PAT：allow-all 照常，但可见租户集合恒为密钥租户（含 Root 共享）；跨租户资源无结果且不泄露存在性。
- 默认租户没有「租户管理员」档；准入检查 3 的测试按租户分别设计。
- `department` 委托范围在调用期展开；服务账号可能被组织侧兜底进「临时访客」部门——安全靠检查 2 的自然人判定，不靠「服务账号永远没有部门」。

---

## 4. 设计与实现（指针）

| 你想知道 | 去哪看 |
|---|---|
| 工作流拆分、人力、依赖、里程碑 | design §4 |
| 请求处理管线（各检查的槽位与归属） | design §3.1 |
| 各工作流的决策与备选 | design §5.A–§5.G |
| 所有人对齐的契约（Principal、端点、错误码、数据、Settings、Redis key、审计 action） | design §6 |
| Alembic 总表 | design §7 |
| 坑 | design §8 + `reference/vibe-049-design.md` §5 |
| 测试策略与 PRD AC 映射 | design §9 |
