# Release Contract — v3.0.0

> 本文件是 v3.0.0（应用工场）版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。
>
> 上游 PRD：《3.0 应用工场 PRD-1 专业开发者通道与应用运行时》v1.5 +
> 伴生《3.0 开放 API 鉴权与身份传递 PRD》v2.0（docs/product/）。
> Spec Discovery 与 11 维代码调研锚点：[000-prd1-discovery/](./000-prd1-discovery/)。
>
> **编号约定**：
> - Feature 编号从 **F049** 起——F043–F048 已被 `features/v3.0.0-beta1/` 占用。⚠️该目录目前**仅存在于 origin/feat/3.0.0-beta1 分支**（未合入主线）；在主线读不到其 release-contract 原文时，以该分支版本为准。
> - 跨 Feature 不变量从 **INV-27** 起。INV-1~7 = v2.6.0 存量（继续有效）；INV-8~26 = v3.0.0-beta1（全部出自 F048 权限重写）——**其生效以 F048 合入 v3.0.0 主线为前提，基线关系随 Discovery 决策 D2 确认**。
> - 历史编号空间：v2.5.0 INV-1~9 与 v2.5.1 INV-T1~T19 是独立编号空间且部分仍有效（部分已被 beta1 INV-24/25 替代），引用时**必须带版本前缀**；本版本裸编号 INV-N 专指 v2.6.0 → v3.0.0-beta1 → v3.0.0 连续链。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| _（随各 Feature spec 编写时登记；Spec Discovery 已预判的候选见下，未经 spec 评审前不生效）_ | — | — |
| （候选）ApiCredential（统一凭据：个人 key `bs-pat-` / 服务账号密钥 `bs-sak-` / 会话 key 派生，同底座） | F049-openapi-auth | 生成/哈希存储/校验/撤销；伴生 PRD R1 |
| （候选）ServiceAccount（不可登录服务账号主体，User.user_type 扩展） | F049-openapi-auth | 伴生 PRD R4 |
| （候选）App / AppVersion / AppInstance（工场应用本体、不可变版本快照、运行实例） | F054-app-domain-runtime | RT-05 语义与既有 flow_version 可变指针语义不同，独立建模 |
| （候选）ResourceTier（资源档位） | F055-app-publish-pipeline | GOV-03 档位实体 + 发布选档/入快照/预检/终检；F056 只读（管理列表展示档位列） |

**规则**：
- 非 Owner Feature 的 AC 中不得出现其他对象的"创建/修改/删除"行为，只能"读取"或"调用" Owner 的 Service
- 新增领域对象时必须先更新本表

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。
（INV-1~7 见 v2.6.0 release-contract；INV-8~26 见 origin/feat/3.0.0-beta1 分支的 v3.0.0-beta1 release-contract，生效前提见编号约定。）

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| _（随各 spec 编写时从 INV-27 起登记；Discovery §4 D6 的 strict fail-closed 边界确认后将登记为首条——注意 D6 与 beta1 INV-19/INV-9 的冲突处理见 discovery.md §4）_ | | | |

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图（规划态，随 spec 定稿逐行确认）

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F049-openapi-auth | — | 伴生 PRD **R1–R7、R9**（R8 限流/配额/幂等属 P2，两册均显式顺延不在本版）：统一凭据底座 + 服务账号主体 + v2 端点鉴权接入 + 三身份模式/受限委托 + 兼容窗口 + GOV-08 凭据底座/审计双归属字段（伴生 PRD §4.8.1 对齐）+ **会话 key 派生机制**（接线随 PRD-2 启用，GOV-08 验收 2/3 会话 key 部分随 PRD-2 验收）。一切 key 类功能的地基（批次 A 首个） |
| F050-personal-api-key | F049 | DEV-01 个人 key + API key 管理页个人 tab + 「我的 API key」+ GOV-07 开放能力层部署 flag 与入口隐藏。与伴生 PRD R1-P1 个人访问令牌是否同一凭据实例 = PRD-1 §6 开放问题 3，spec 定夺 |
| F051-model-protocol-gateway | F050 | DEV-02 OpenAI/Anthropic 兼容直连面 + GOV-04 按 key 用量账单 |
| F052-mcp-server-face | F050 | DEV-02 MCP 工具面（应用数据/状态日志两工具随批次 B 接线）+ 统一检索门面（strict fail-closed + 声明白名单收窄，GOV-05 运行时/F057 共用） |
| F053-dev-cli-skills | F050, F051, F052 | DEV-03 技能包 + DEV-04 CLI（login/skills sync/dev；deploy/logs 随 F055 启用）+ DEV-05 本地身份注入 + 安装件分发 |
| F054-app-domain-runtime | F049 | RT-01/07/08 + 托管运行契约：app 领域模型/状态机/FGA app 类型/实例编排/per-app 数据库与附件/代码快照 + **GOV-03 实例配额执行闸门**（复用 tenant.quota_config + QuotaService，实例拉起/重新启用内置校验，先于档位实体存在——F054 单独合入无「无护栏窗口」）+ PRD-2 最小面 **WB-13 运行日志、WB-06 数据面**（体量大，spec 阶段可再拆） |
| F055-app-publish-pipeline | F054, F049 | RT-03/04/05 + GOV-02 + **GOV-05 主体**（模型/密钥引用运行时注入通道、「发布审批即授权」、能力收回→明确错误态与 owner 失效提示；检索范围规则的门面在 F052）+ **GOV-03 资源档位**（ResourceTier 实体 + 档位管理 tab + 发布选档/入快照/预检/终检/待上线态）+ GOV-08 应用 token + DEV-06（本册恒「在本地」）+ DEV-04 deploy/logs + 事件触达接线 + PRD-2 最小面 **WB-14 发布面、WB-15 版本差异**。含审批中心前置修复（tenant_admin resolver、withdraw 终态守卫，属行为变更需 release note 声明） |
| F056-app-square-governance | F054, F055 | RT-02 广场接入 + GOV-01 + GOV-04 审计扩展 + GOV-09 + PRD-2 最小面**「我的应用列表」**（同一入口页并列 tab）+ GOV-03 租户实例配额设定 UI 与用量条（含配额覆盖写语义修复）+ GOV-07 剩余部分（角色权限配置面与工场运行时层开关；开放能力层 flag/入口隐藏已随 F050、未部署引导页已随 F054、CLI 新建权限校验已随 F055）（体量大，spec 阶段可再拆） |
| F057-bisheng-sdk | F049, F051, F052, F054 | DEV-07 五件套 + 开发者指南（appdb/storage 面依赖 F054）。DEV-07 验收 2 依赖 PRD-2 WB-01 模板、随 PRD-2 验收；本版验收范围 = 验收 1/3 |

**未映射项登记**：GOV-05 密钥引用的录入面（PRD-2 WB-05）不在 PRD-1 §1 最小承载面清单——密钥引用能力随本册交付还是顺延，待产品确认（Discovery §4 次级决策）。

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突（存量分配见 v2.6.0 release-contract 与 `common/errcode/`）。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| 260 | open_api（开放 API 鉴权，26001–26012 见伴生 PRD 附录 C） | F049（规划，spec 时确认与 `common/errcode/` 无冲突） |
| _待分配_ | app_factory（应用工场，模块号 spec 阶段核对 errcode 目录后分配） | F054/F055/F056 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-08-06 | 初始化 v3.0.0 契约：登记编号约定（F049 起 / INV-27 起）、PRD-1 九个 Feature 的规划依赖图（表 3）、领域对象候选（表 1，未生效）；正式登记随各 spec 评审进行 | 全部 |
| 2026-08-06 | 对抗校验修正：GOV-05 主体归属 F055（原漏映射）；会话 key 派生归 F049、接线随 PRD-2；F049 范围收为 R1–R7+R9（R8 P2 顺延）；ResourceTier 由 F056 移至 F055 并把实例配额执行闸门划入 F054（消除依赖倒挂与无护栏窗口）；PRD-2 最小承载面逐面指名；beta1 契约来源分支与 INV-8~26 条件生效、历史编号空间说明补齐 | 表 1/表 3/编号约定 |
