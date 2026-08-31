# Spec Discovery — 开放 API 鉴权与身份传递（落 `feat/3.0.0-beta1`）

> **状态**: ★ 已裁定（2026-08-31）——用户决定：**PRD 全部需求（含 P1、P2）一起设计、先出设计、按工作流多人分工**。
> 因此 §1 的「拆 4 个 Feature、分 2 批」方案**不采纳**，改为**一个 Feature（F053）+ 7 个工作流**；§4 的决策 A（范围）= 全量，B（扩展位）= 原样搬、开关默认关，C（share-token）= 随本 Feature 做，D（目录）= `features/v3.0.0-beta1/053-openapi-auth-and-identity/`。
> 设计见 [../053-openapi-auth-and-identity/design.md](../053-openapi-auth-and-identity/design.md)。以下正文保留作调研记录（§2 代码基线事实与 §3 差异清单仍有效）。
> **日期**: 2026-08-31
> **上游 PRD**: 《3.0 开放 API 鉴权与身份传递 PRD》**v2.4**（飞书 `WItBws4zUiGP6YkrpUccBo6sn8e`，2026-08-27/28）；同一文件已存于 `3.0-vibe:docs/product/`，落分支时随第一个 Feature 一并拷入 `docs/product/`
> **代码基线**: `feat/3.0.0-beta1` @ `972397fbe`；参考实现 `3.0-vibe`（merge-base `db18f31e9`，vibe 基于 beta1 分叉）
> **本文目的**: 只回答「拆几个 Feature、各自边界、先后顺序、哪些代码能从 vibe 搬、PRD v2.4 相对 vibe 上旧 spec 改了什么」。不写 How。

---

## 1. 结论先行

PRD 覆盖 R1–R10，P0 + P1 + P2。建议**拆 4 个 Feature、分 2 批**，P2（限流 / 配额 / 幂等 / IP 白名单）本轮不做：

| 编号 | Feature | 承接 PRD | 批次 | 与 vibe 的关系 | 估算 |
|---|---|---|---|---|---|
| **F053** | 开放 API 鉴权底座（默认拒绝 + 服务账号密钥 + 资源归属人 + 全端点接入 + 管理界面） | R1 / R4 / R5 / R6 / R9 + R3 铁律 1–3 | **批次 1** | vibe `049-openapi-auth-baseline` 的移植：Wave 1–2（33 任务）代码可整体 cherry-pick；Wave 3–6（43 任务：38 个存量端点打标 + WS 鉴权 + 分享链接通道 + 资源授权页 + 既有缺陷修复 + 配置项移除）需在 beta1 上实做 | 底座已有 → 约 **7~8 人天**（PRD 原估 11~12） |
| **F054** | 身份传递（两种身份模式 + 受限委托五道准入 + 审计双归属 + 裸 `user_id` 收口 + 检索文件级过滤） | R2 / R3 委托 / R7 / §4.4.6 | **批次 1** | vibe `050-identity-modes` 只有 spec.md（已评审），无 design / 代码。spec 可改编后复用。§4.4.6 文件级过滤在 vibe 归 F052「统一检索门面」（依赖应用工场 MCP 面）——beta1 无应用工场，**归入本 Feature 直接改 `_aretrieve_chunks_for_*` 两个分支** | **12~14 人天** |
| **F055** | 个人访问令牌（自然人主体 + 个人中心自助签发 + 级联失效 + 治理三闸门 + 技能包 zip） | R10 / §3.5 场景四 | **批次 2** | vibe 上**零开工**（PRD v2.4 新增）。凭据底座复用 F053（`SUBJECT_RESOLVERS` 加一个枚举 + 解析函数，附录 E.6）；**beta1 无 `dev_toolkit` 模块**，技能包分发端点须最小化移植或新建 | **12~15 人天**（含两层开关 1~2） |
| **F056** | 日常模式会话开放（选模型 + 挂知识库 / 平台工具 / 附件 + 服务端多轮 + 流式 / 非流式） | §4.6.3 / `chat:invoke` 消费端点 | **批次 2（可延）** | vibe `058-openapi-responses` 只有 spec.md；契约形态归 design（D9）。依赖 F054（模式 D 是主场，PRD 明确不可只出模式 S 版本） | PRD 原估 12~15，按 D9 改判后**须重估、应显著下调** |

**硬约束**：F053 **不得脱离 F054 单独对外发版**（PRD §4.9：裸 `user_id` 参数随本版一并移除、不留过渡期；F053 期该参数仍按旧语义解析）。因此批次 1 = F053 + F054 合并发版。

**编号说明**：beta1 的 `release-contract.md` 已用到 F052，本轮从 **F053** 起。⚠️ vibe 分支上 F049–F052 指的是另一组 Feature（`049-openapi-auth-baseline` 等），引用 vibe 文档时**必须带分支前缀**，避免与 beta1 的 `049-knowledge-space-children-read-optimization` 混淆。

---

## 2. 代码基线事实（beta1 现状，2026-08-31 核实）

| 项 | beta1 现状 | 影响 |
|---|---|---|
| `src/backend/bisheng/open_api/` | **不存在** | 凭据底座整体从 vibe 搬 |
| `/api/v2/**` | **43 个 HTTP + 2 个 WS，全部匿名**（`open_endpoints/api/endpoints/` 8 个文件）；身份靠 `open_endpoints/domain/utils.py` 的 `get_default_operator*()` / `resolve_operator(user_id)` | PRD 附录 B.1 逐端点改造清单适用；数量比 PRD 写的 42 多 1，落 spec 时重数 |
| `default_operator` / `enable_guest_access` | 在 `open_endpoints/` 内取用 | 随 F053 移除（PRD §4.9） |
| client `pages/standaloneChat/` | 存在（两个免登录分享页的真身，走 v2 WS） | F053 锁 v2 WS 后这两页会断——须随 F053 做 share-token 通道（vibe 049 决议-1），否则分享页失效 |
| `dev_toolkit/` | **不存在**（vibe F053 应用工场 CLI 的产物） | F055 技能包分发端点无现成件；`linsight/builtin_skills/` 三个 office 包的目录规范可作技能包结构参照 |
| `api_credential` / `service_account` 表 | vibe 上**无 Alembic 迁移**，只靠 `create_all` | F053 移植时补迁移 |
| 权限判定短路 / `_visible_tenant_ids` | 与 vibe 同源（beta1 已含 F048） | PRD 附录 E.5 / E.6 取证在 beta1 上成立 |

### 2.1 从 vibe 搬代码的可行性（已在临时 worktree 实测）

按 `a15f06135 → 86e52f90b → 43e73bfc5 → c5989ffd6 → e31c35732` 顺序 `cherry-pick` 到 beta1：**85 个文件 / +10.5k 行，真冲突只有三处**——

1. 多语言文件 9 个（`api_errors` 三语 × packages / platform / client 生成物）：两侧各自追加了 key，合并即可（生成物须重跑脚本不手改）
2. `api/v1/endpoints.py`（`get_env` 增 `open_platform_enabled` 字段，与 beta1 同函数其他改动相邻）
3. `test/permission/test_f048_schema_contract.py`（`user_type` 列断言）

另 vibe 提交带的 `features/v3.0.0/049-*` 文档**不搬**——beta1 侧按本 Discovery 新建 F053 目录重写 spec / design / tasks。

被这 5 个提交**修改**（非新增）的 beta1 既有文件共 33 个，全部为小改：`user.py`（加 `user_type` 列 + DAO 默认过滤）、`auth.py`（`LoginUser.open_api_principal`）、`admin_scope.py`（管理前缀）、`tenant_filter.py`（模块注册）、`settings.py`（`open_platform` / `open_api` 配置）、`api/router.py` + `main.py`（挂载）、`grant_subject_service.py`（选人排除）、`audit_log.py`（动作登记）、`SystemPage/index.tsx`（tab）等。

---

## 3. PRD v2.4 相对 vibe 上旧 spec 必须改的点

vibe 的 `049` spec / design 写于 2026-08-17（PRD v2.1），**以下结论已被推翻或不适用于 beta1**，改编时逐条处理：

| # | vibe 旧结论 | 现状 | 处置 |
|---|---|---|---|
| 1 | 「个人访问令牌整条否决；全平台只有服务账号一类主体、`bs-sak-` 一类凭据」（049 spec 排除项、决议-4） | PRD v2.4 **D13 改判：做**（`bs-pat-`，自然人主体，§4.10） | F053 spec 排除项改为「随 F055」；底座 `SUBJECT_RESOLVERS` 与前缀提取参数化（附录 E.6 两处约 5 行） |
| 2 | 三扩展位 `model:invoke` / `identity:read` / `app:manage` 的运行期消费随 F051–F053（MCP / 模型协议面 / CLI） | beta1 **无应用工场**，三面不存在 | 见 §4 决策 B |
| 3 | 「服务账号详情页接入信息区（MCP 地址 / base URL / CLI 下载）随 F053」 | 同上 | 不做 |
| 4 | 「应用运行期凭据由 F055 随发布自动签发」；托管应用主体类型 | beta1 无托管应用 | 底座保留 `subject_kind` 可扩展枚举即可，不登记 `app` 主体 |
| 5 | 「§4.4.6 文件级过滤随 F052 统一检索门面」 | beta1 无 F052 | 归入 F054，直接改两个检索分支（附录 E.3 落点） |
| 6 | 「AC-33 任何身份头一律 403」 | 仍是 F053 期形态，F054 赋正式语义 | 保留 |
| 7 | 日常模式会话对标 OpenAI Responses 子集（vibe 058 spec 依据 PRD v2.1） | PRD v2.3 **D9 改判：形态归 design**；D11 / D12 泛化 | F056 spec 须按 v2.4 §4.6.3 重写，vibe 058 spec 只作参考 |
| 8 | 错误码：vibe 已启用 `26001–26004 / 26012 / 26020–26031`；PRD 附录 C 另定义 `26005–26011 / 26015–26017 / 26040–26043` | beta1 `docs/constitution.md` C5 登记表**尚无 260 段**（vibe 那份改动随 cherry-pick 带过来） | F053 落码时登记 260 段并注明 F054 / F055 预留段；`26040+` 归 F055 |

---

## 4. 待 ★ 用户裁定

| # | 决策 | 建议 | 备选 |
|---|---|---|---|
| **A** | 本轮范围：批次 1（F053 + F054）之后，批次 2 做 F055 PAT，**F056 日常模式会话是否本轮做** | **F055 做、F056 延后**——PAT 是 v2.4 的新增诉求、有真实客户场景；日常模式会话无客户催、且 D9 改判后估算须重做 | 四个全做（约 45 人天）；或只做批次 1 |
| **B** | 三扩展位（应用工场）在 beta1 上的处置 | **代码原样搬、`open_platform.enabled=False` 默认关**——注册表里留着、界面不出现、签发被拒（vibe 049 AC-13 WHERE 分支已实现）。零成本，将来与 vibe 合并不打架 | 从注册表删掉（干净但日后合并冲突） |
| **C** | share-token 通道（两个免登录分享页改走 `share_link`，vibe 049 决议-1；PRD §4.6.1「浏览器直连：子协议或票据换取」的落地形态） | **随 F053 做**——不做则锁 v2 WS 即打断分享页；这是 PRD 没细写但 beta1 必须补的一块（vibe 上也未实做，Wave 4） | 分享页暂改走 `/api/v1` 登录态（改动面更大） |
| **D** | Feature 目录归属 | `features/v3.0.0-beta1/053~056-*`，release-contract 表 1 登记 `ApiCredential` / `ServiceAccount` 两个领域对象（Owner = F053）、新增 INV-29+ | 另开 `features/v3.0.0/`（与 vibe 同名目录、编号撞车） |

A / B / C 任一改变都会改 F053 spec 的范围边界，故先定再写 spec。D 按建议直接执行，无需单独确认。

---

## 5. 建议执行顺序

```
① release-contract.md 登记 F053–F055（表 1 / 表 2 / 表 3 / 错误码 260）
② F053 spec.md（改编 vibe 049 spec，按 §3 修订）→ /sdd-review → ★
③ F053 design.md（改编 vibe 049 design，补 Alembic / 无应用工场差异）→ /sdd-review → ★
④ 建分支 feat/v3.0.0-beta1/053-openapi-auth-baseline；cherry-pick 5 提交 + 解冲突 + 补迁移（= vibe Wave 1–2 落地）
⑤ F053 tasks.md：只列 beta1 上要实做的 Wave 3–6 + 移植修补项 → 实现
⑥ F054 spec（改编 vibe 050 spec）→ design → tasks → 实现   ← 与 ⑤ 后半可并行
⑦ 批次 1 合并发版（F053 + F054 同时）
⑧ F055 PAT 全新 spec → design → tasks → 实现
```
