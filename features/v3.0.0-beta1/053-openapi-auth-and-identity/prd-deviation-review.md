# F053 开放 API 鉴权：实现与 PRD 偏离清单（评审转交）

日期：2026-09-09　范围：`src/backend/bisheng/open_api/` 及相关模块　基准：`docs/product/3.0 开放 API 鉴权与身份传递 PRD.md`（含 §7 决策记录 D1–D20）
性质：代码静态审计，未跑接口。首轮对 `feat/3.0.0-beta2`（da2be5697）审计，随后按 `feat/3.0.0-beta1` 最新提交（59b27d1c1，2026-09-09 20:27）逐项复核；行号以 beta2 为准，复核结论以 beta1 为准。

## 结论

实现总体忠于 PRD，端点接入、委托、个人令牌、审计、检索文件级过滤都已落地。design §2.1 列出的 10 项改判中有 5 项偏离 PRD 且未经产品追认。其中两项实现事故（D17、D19）highway 已于 9 月 9 日在 beta1 上修复（f6bf9f51f），尚未合入 beta2；其余需产品裁定后改 PRD 或改代码。

## 一、已修复，待合入 beta2（beta1 f6bf9f51f，2026-09-09）

| # | 决议 | 现状 | 期望 | 锚点 |
|---|---|---|---|---|
| 1 | D17：管理员持有的个人令牌继承管理员短路，但可见租户集合恒为密钥租户 | beta2 上对所有 v2 主体硬编码 `super_admin=False`（`open_api/api/dependencies.py:98-104`） | **beta1 已修**：自然人主体解析时加载 `_check_is_global_super` / `is_tenant_admin` 注入 `PermissionActor`，租户集合限密钥租户 | 请 dolphin 合入 beta2 |
| 2 | D19（9 月 3 日拍板）：换租户令牌不失效、随人迁移 | beta2 上换租户仍 `cascade_revoke`（`user_tenant_sync_service.py:353-366`） | **beta1 已修**：改为 `PersonalTokenService.migrate_tenant` | 同上；design.md:290 的旧口径请同步改 |

## 二、需产品裁定（改 PRD 还是改代码，二选一）

| # | 决议 | 现状 | 备注 |
|---|---|---|---|
| 3 | D4：服务账号复用用户表，用类型字段区分 | 独立 `service_account` 表、自增主键、与 `user` 无关系（design 第 56、93 行明写作废 vibe 写法） | 工程上更干净，免掉登录守卫、选人排除、对账豁免三项成本；但推翻 PRD 已定条目。若追认，需回写 PRD §4.5 与 D4，并补错误码表中 26012 的去留说明 |
| 4 | 身份头名 `X-Bisheng-On-Behalf-Of` | 改为 `X-On-Behalf-Of`（design K20），spec 第 50 行仍写旧名，PRD 的 AC-6/AC-10/AC-26/AC-38/AC-P15 逐字失效 | 与 OAuth OBO 同名更易混读。定一个名字，三处对齐 |
| 5 | §4.6.3：日常模式本次交付含知识库挂载、非流式、业务上下文指令；对外契约不暴露平台内部概念；会话列表/历史明确不做 | 无知识库入参（`to_internal()` 硬写 `use_knowledge_base=None`）；只有 SSE；无业务上下文字段；对外 schema 暴露 `clientTimestamp/parentMessageId/overrideParentMessageId/responseMessageId/isCreatedByUser/isContinued/generation`；新增 `GET /api/v2/chat/list`、`GET /api/v2/chat/info` | 锚点 `open_api/domain/schemas/workstation.py:25-39,52`、`open_endpoints/api/endpoints/workstation.py:40-45`、`chat.py:15-33`、`domain/scopes.py:50-57`。裁定：补齐还是降级到下一版；两个新端点是否追认 |
| 6 | §4.9 铁律 1：移除固定身份兜底、`default_operator` 与 `enable_guest_access` 废弃 | v2 已清干净；默认操作员搬到新开的匿名 `/api/v3` 面继续以 `enable_guest_access` 为闸（design 第 96 行「只从 v2 移除」） | 缓解措施到位（`super_admin=False`、租户与资源双重收窄、仅已发布资源）。裁定是否追认 v3 匿名面 |

## 三、次要缺陷（均按 beta1 最新提交复核仍成立）

- 个人令牌默认有效期 30 天，PRD §4.10.5 为 365 天：`models/open_api_tenant_setting.py:13` 及迁移 server_default。
- 技能包缺 `meta.json` 与 `references/api.md`（PRD §4.10.8 必备件表）：`services/skill_pack_service.py:19-56`。分发路径自建 `/api/v1/open-api/skill-packs/{pack}`，PRD 点名的 `/api/v1/dev-toolkit/skills/{pack}` 在两个分支都不存在，PRD 该处取证已过期。
- `delegate` 位与 `model:invoke / identity:read / app:manage` 三扩展位未做互斥硬阻断（PRD §4.2.4）：`services/credential_service.py:260-275`。三位当前不可签发，点亮即成漏洞。
- 交付文档 `openapi-v2-key-auth-api.md:34` 的 curl 示例传 `messages` 且 `clientTimestamp:0`，schema 是 `extra="forbid"` 且该字段为字符串，照抄必 400（beta1 最新提交仍如此）。
- 存量对客文档未清：`docs/api/filelib-retrieve.md:26` 仍写「网络层负责访问控制」，`docs/api/知识库接口文档.md:27,211,292` 仍把 `user_id` 作为入参（PRD AC-P22 / AC-26）。
- 错误码表少 26012（服务账号禁止登录）；26029 语义与 vibe 侧不同（vibe：服务账号不可作资源侧授权主体；beta2：不能当归属人）。

## 四、给后续合并 3.0-vibe 的提醒

- 两侧 `service_account` / `api_credential` 同名不同构（主键、外键、列集不同）。beta2 迁移带 `table_exists` 幂等守卫，跑过 vibe 的库升级会跳过建表、留旧表、启动即崩且无告警；`subject_kind` 的 CHECK 不接受 vibe 的 `hosted_app`。
- vibe 独有需要补回的：`open_api_subject` 端点级鉴权工厂、权限位注册表的分组/文案/高危提示/`visible_scopes`、错误码 26028；合计不到 200 行。vibe 的密钥泄漏扫描器要补登记 `bs-pat-` 前缀（PRD §4.2.6），beta 线没有扫描器，与 highway 无关。
- 应用工场（app_publish / app_runtime / dev_toolkit）在 beta2 上不存在；vibe 侧三处引用 open_api 的符号适配不到 60 行，难点是托管应用的运行期凭据主体要进 beta2 的数据模型。

## 五、口径订正（审计时发现 PRD 或口头说法有误）

- 不暴露的会话端点是 6 个 `/chat/*`（PRD §4.6），不是 8 个。
- D9 已改判为「PRD 不裁定日常模式形态」，不用 OpenAI Responses 子集不算偏离；偏离的是 §4.6.3 的业务入参与硬边界。
