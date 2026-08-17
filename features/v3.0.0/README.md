# v3.0.0 Feature 索引（应用工场）

**版本目标**：交付《3.0 应用工场 PRD-1》**v2.0**——专业开发者通道（DEV）、应用运行时与发布（RT）、治理与管理面（GOV）共 21 项，及伴生《3.0 开放 API 鉴权与身份传递 PRD》**v2.1** 的 v2 开放 API 鉴权改造。界面承载面落 platform「构建 → 应用」（托管应用 = 与工作流 / 助手并列的第三种类型），运行时 compose / k8s 双形态。

**版本契约**：[release-contract.md](./release-contract.md)
**Spec Discovery**：[000-prd1-discovery/discovery.md](./000-prd1-discovery/discovery.md)（含 11 维代码调研锚点 research/ 与 F048 基线重核 baseline-recheck.md；**2026-08-17 已按 PRD-1 v2.0 重排为拆分 v2**）

> ⚠️ **推送前必读**：本分支 `3.0-vibe` 汇集了应用工场与开放 API 鉴权的全部产品文档与调研记录，其中 `000-prd1-discovery/research/` 与 `docs/product/3.0 开放 API 鉴权与身份传递 PRD.md` **含未修复安全缺口的行级定位**。origin 是公开仓，**未经确认不得推送本分支**。

> 编号说明：F043–F048 已被 `features/v3.0.0-beta1/` 占用（该目录仅存在于 origin/feat/3.0.0-beta1 分支、未合入主线），本版本从 F049 起；拆分 v2 新增 F058 / F059。

---

## Feature 列表（拆分 v2，2026-08-17 ★ 已过；MVP-114 纵切见 [mvp-114-path.md](./mvp-114-path.md)；**spec 层 11/11 已写、9 份定稿**）

| # | Feature | 批次 | 状态 | 依赖 | 覆盖 |
|---|---------|------|------|------|------|
| F049 | openapi-auth-baseline | A | ✅ Spec 定稿（65 AC）· ✅ design 已评审（13 决策 / 27 坑，双审 26 条修订）· ✅ tasks 已拆解（76 任务，40 条 [MVP-114]，65 AC 全覆盖）· 实现 0/76 | — | 伴生 P0：凭据底座 / 服务账号（含资源归属人）/ 全端点接入 / 管理界面 / 零迁移升级；三扩展位登记 |
| F050 | identity-modes | A | 📝 Spec 已写（48 AC，独立审查中） | F049（+F052） | 伴生 P1：两种身份模式 / 受限委托 / 审计双归属 / 裸 `user_id` 收口 / `delegate` 位与互斥 |
| F051 | model-protocol-gateway | A | ✅ Spec 定稿（36 AC，经独立审查修订） | F049 | DEV-02 模型协议面（仅 OpenAI 兼容）+ 模型调用逐条审计 |
| F052 | mcp-server-face | A | ✅ Spec 定稿（47 AC，经独立审查修订） | F049 | DEV-02 MCP 六类工具 + 统一检索门面（文件级 fail-closed） |
| F053 | dev-cli-skills | A 尾 / B | ✅ Spec 定稿（55 有效 AC，经独立审查修订） | F049, F051, F052 | DEV-03 两包 / DEV-04 CLI 四命令 / DEV-05 本地身份注入 / DEV-01 接入信息区 |
| F057 | bisheng-sdk | A 尾 / B | ✅ Spec 定稿（36 AC，经独立审查修订） | F052, F053（storage 依赖 F054） | DEV-07 三件套 + 开发者指南 |
| F058 | openapi-responses | A | ✅ Spec 定稿（36 AC，经独立审查修订） | F050 | 伴生 P1 日常模式会话 Responses 契约（不在 PRD-1） |
| F054 | app-domain-runtime | B | ✅ Spec 定稿（65 AC，经独立审查重写）· 📝 design / tasks 工作流进行中 | F049 | 托管应用领域模型 / compose 运行时 / app-proxy / RT-01 / RT-07 / RT-08 / GOV-01 类型注册 / 详情页壳 WB-13 · WB-06 / GOV-10 层开关 |
| F055 | app-publish-pipeline | B | ✅ Spec 定稿（65 AC，经独立审查重写）· design / tasks 待启动 | F054, F049, F051, F052 | RT-03 / RT-04 / RT-05 / deploy 管线 / GOV-02 预置审批流 / GOV-03 档位 / GOV-05 能力总线 / WB-14 · WB-15 |
| F056 | app-square-governance | B | ✅ Spec 定稿（45 AC，经独立审查修订）· design / tasks 待启动 | F054, F055 | RT-02 广场 / GOV-01 授权交互 / GOV-04 审计 / GOV-07 权限控制 / 事件触达 |
| F059 | k8s-runtime-backend | B | ✅ Spec 定稿（42 有效 AC，经独立审查修订） | F054 | GOV-10 k8s 形态 + 镜像构建与分发（方案 F113，不可裁剪） |

批次 A = 开放能力层（可独立于工场运行时交付，GOV-10）；批次 B = 工场运行时层。建议顺序：A：F049 → F052 → F051 → F053 → F050 →（F058）→ F057；B：F054 → F055 → F056，F059 与 F055 并行。

---

## SDD 工作流

1. Spec Discovery → ★ 用户确认（拆分 v2 已过 ★；2026-08-17 起用户授权全自动模式，后续 ★ 按建议自动拍板并记录）
2. 编写 spec.md → `/sdd-review <dir> spec` → ★（F049 已过；其余按 MVP 纵切顺序）
3. 编写 design.md → `/sdd-review <dir> design`（Constitution Check）→ ★ 用户确认
4. 编写 tasks.md → `/sdd-review <dir> tasks`
5. 创建 Feature 分支 `feat/v3.0.0/{NNN}-{name}`（尽早建，文档与代码都在分支上）
6. 逐任务执行 → `/task-review` → 打勾
7. `/e2e-test`（强制）
8. `/code-review`
9. 合并

---

## 变更历史

| 日期 | 变更 |
|------|------|
| 2026-08-06 | 初始化 v3.0.0 版本目录：PRD-1 Spec Discovery 产出（000-prd1-discovery/）+ 契约初版 + 九 Feature 规划索引。 |
| 2026-08-06 | F049 spec 初稿 + 四项待澄清拍板（个人 key 整条取消）；F050 更名 identity-modes；F051/F052 依赖放宽为 F049。 |
| 2026-08-15 | F049 spec 对齐伴生 PRD v2.0（兼容窗口废止、服务账号不进选人场景、主体侧授权唯一入口）。 |
| **2026-08-17** | **按 PRD-1 v2.0 + 伴生 v2.1 重做 spec 层地基**：Discovery 拆分 v2（11 个 Feature，新增 F058 / F059；F050–F057 范围重排）+ release-contract 表 1 / 表 2（INV-29 修正、INV-31 新登记、候选 INV-32~36）/ 表 3 重写 + F049 spec 整体重写（AC 47 → 65）。待第二次 ★。 |
