# v3.0.0 Feature 索引（应用工场）

**版本目标**：交付《3.0 应用工场 PRD-1》**v2.0**——专业开发者通道（DEV）、应用运行时与发布（RT）、治理与管理面（GOV）共 21 项，及伴生《3.0 开放 API 鉴权与身份传递 PRD》**v2.1** 的 v2 开放 API 鉴权改造。界面承载面落 platform「构建 → 应用」（托管应用 = 与工作流 / 助手并列的第三种类型），运行时 compose / k8s 双形态。

**版本契约**：[release-contract.md](./release-contract.md)
**Spec Discovery**：[000-prd1-discovery/discovery.md](./000-prd1-discovery/discovery.md)（含 11 维代码调研锚点 research/ 与 F048 基线重核 baseline-recheck.md；**2026-08-17 已按 PRD-1 v2.0 重排为拆分 v2**）

> ⚠️ **推送前必读**：本分支 `3.0-vibe` 汇集了应用工场与开放 API 鉴权的全部产品文档与调研记录，其中 `000-prd1-discovery/research/` 与 `docs/PRD/3.0-beta2/3.0 开放 API 鉴权与身份传递 PRD.md` **含未修复安全缺口的行级定位**。origin 是公开仓，**未经确认不得推送本分支**。

> 编号说明：F043–F048 已被 `features/v3.0.0-beta1/` 占用（该目录仅存在于 origin/feat/3.0.0-beta1 分支、未合入主线），本版本从 F049 起；拆分 v2 新增 F058 / F059。

---

## Feature 列表（拆分 v2，2026-08-17 ★ 已过；MVP-114 纵切见 [mvp-114-path.md](./mvp-114-path.md)；**状态核对于 2026-10-08**）

勾选数取自各 Feature 的 tasks.md。未勾选的任务全部是需要 114 真机、CI 中间件或用户拍板的验收项，不是未写的代码（逐条见 tasks.md）。

| # | Feature | 批次 | 状态 | 依赖 | 覆盖 |
|---|---------|------|------|------|------|
| F049 | openapi-auth-baseline | A | 🗄️ spec / design / tasks 存档 · **实现由 `feat/3.0.0-beta2` F053 承接**（2026-09-10，见 [beta2-openapi-base-migration.md](./beta2-openapi-base-migration.md)）；tasks 33/76 为归档时状态，余项不再在本目录推进 | — | 伴生 P0：凭据底座 / 服务账号（含资源归属人）/ 全端点接入 / 管理界面 / 零迁移升级；三扩展位登记 |
| F050 | identity-modes | A | 📝 仅 Spec（48 AC，独立审查 15 条待修订）· 无 design / tasks / 实现。`delegate` 位与委托范围已由发版线 beta2 F053 交付；两种身份模式、受限委托准入、审计双归属、裸 `user_id` 收口未做 | F049（+F052） | 伴生 P1：两种身份模式 / 受限委托 / 审计双归属 / 裸 `user_id` 收口 / `delegate` 位与互斥 |
| F051 | model-protocol-gateway | A | ✅ 实现完成 27/30 · 余 T025 托管应用端到端、T027 本地引擎手动验证、T028 审计与账本核对（均需 114） | F049 | DEV-02 模型协议面 `/api/v2/model/v1`（仅 OpenAI 兼容）+ 模型调用逐条审计 |
| F052 | mcp-server-face | A | ✅ 实现完成 33/35 · 余 T104 集合相等 + fail-closed 存储层断言、T302 真 MCP 客户端端到端（均需 CI 中间件） | F049 | DEV-02 MCP 六类工具 `/api/v2/mcp` + 统一检索门面（文件级 fail-closed） |
| F053 | dev-cli-skills | A 尾 / B | ✅ 实现完成 52/53 · 余 T033 114 部署与手动验证清单 | F049, F051, F052 | DEV-03 两包 / DEV-04 CLI 四命令 / DEV-05 本地身份注入 / DEV-01 接入信息区 |
| F057 | bisheng-sdk | A 尾 / B | ✅ 实现完成 42/45（新包 `src/bisheng-sdk`）· 余 T032 / T042 114 验证、T040 评测跑分（达标线 5/5 还是 6/6 待拍板） | F052, F053（storage 依赖 F054） | DEV-07 三件套 + 开发者指南 |
| F058 | openapi-responses | A | 📝 仅 Spec（36 AC 定稿）· 无 design / tasks / 实现 | F050 | 伴生 P1 日常模式会话开放（不在 PRD-1） |
| F054 | app-domain-runtime | B | ✅ 实现完成 102/104 · 余 T074 compose 形态从未真机起过（配置面已交付并有机器守卫）、T096 E2E + 页面手动清单 | F049 | 托管应用领域模型 / compose 运行时 / app-proxy / RT-01 / RT-07 / RT-08 / GOV-01 类型注册 / 详情页壳 WB-13 · WB-06 / GOV-10 层开关 |
| F055 | app-publish-pipeline | B | ✅ 实现完成 71/72 · 余 T049 114 部署与手动验证清单 | F054, F049, F051, F052 | RT-03 / RT-04 / RT-05 / deploy 管线 / GOV-02 预置审批流 / GOV-03 档位 / GOV-05 能力总线 / WB-14 · WB-15 |
| F056 | app-square-governance | B | 🟡 实现 32/33 · 余 T021 114 闭环手动验证；**GOV-04 三类记录无查询入口，待拍板**（见下文「未结事项」） | F054, F055 | RT-02 广场 / GOV-01 授权交互 / GOV-04 审计 / GOV-07 权限控制 / 事件触达 |
| F059 | k8s-runtime-backend | B | 📝 仅 Spec（42 有效 AC 定稿）· 无 design / tasks / 实现；MVP-核心登记为全部顺延（[mvp-114-path.md §6](./mvp-114-path.md)） | F054 | GOV-10 k8s 形态 + 镜像构建与分发（方案 F113，不可裁剪） |

批次 A = 开放能力层（可独立于工场运行时交付，GOV-10）；批次 B = 工场运行时层。建议顺序：A：F049 → F052 → F051 → F053 → F050 →（F058）→ F057；B：F054 → F055 → F056，F059 与 F055 并行。

---

## 当前状态（2026-10-08）

**代码面**：PRD-1 的功能代码于 2026-09-16 全部写完并合入 `3.0-vibe`（`59607c4f4`）。2026-09-18 按实现侧接线逐项验收 21 项：17 项完整交付，3 项是 PRD 与实现不一致，1 项是真缺口（GOV-04）。验收修掉了 3 个缺陷（`a0770eb67` 及之前两个提交）：应用发布可被配成免审（绕过 INV-34）、运行期凭据签发与回收不计审计（F055 AC-58）、v2 filelib 18 条断言失效。此后应用工场代码没有新的功能提交，`3.0-vibe` 只合入发版线 beta3 的改动。

**部署面**：114 运行本分支，剧本链路（CLI deploy → 审批 → 上线 → 同租户非管理员经部门授权访问 → logs → 下线删除）已跑通。应用工场尚未合入发版线：`feat/3.0.0-beta3` 不含 `app_runtime` / `app_publish` / `runtime-manager` / `app-proxy`；含 `app` 资源类型的 FGA 模型（本分支命名 `f048-v5-app`）在正式合入时才发布到 116 / 105。

### 未结事项

| 类别 | 事项 | 位置 |
|---|---|---|
| 待拍板 · 真缺口 | GOV-04：`model_call_record` / `AppCapabilityCallRecord` / `app_access_log` 只写不读，PRD-1 GOV-04 验收要点 1、3 不可达。三个方案：A 审计页加独立查询 tab（推荐）、B 只补端点、C 本版不做并同步改 PRD。选 A 或 B 时，运行期凭据审计行的 `metadata` 顺带补 `app_id` | [056 tasks.md](./056-app-square-governance/tasks.md) 末节 |
| 待拍板 · PRD 与实现不一致 | RT-04 / GOV-05 密钥引用：F055 spec 按 Discovery N4 划归 PRD-2，本册不做；PRD-1 正文仍把它列入 RT-04 定义与验收要点 | [055 spec.md](./055-app-publish-pipeline/spec.md) |
| 待拍板 · PRD 与实现不一致 | GOV-03 轻量档：PRD 写 1C/2G，实现为 0.5C/1G（F055 spec 决议-10 于 2026-09-09 下调，PRD 未同步） | [055 spec.md](./055-app-publish-pipeline/spec.md) |
| 待拍板 · PRD 与实现不一致 | GOV-10 k8s：PRD §1.4 列为本册功能，[mvp-114-path.md §6](./mvp-114-path.md) 登记为顺延 | F059 |
| 待拍板 | F057 T040 评测达标线 5/5 还是 6/6 | [057 tasks.md](./057-bisheng-sdk/tasks.md) |
| 114 验收 | F051 T025 / T027 / T028、F053 T033、F055 T049、F056 T021、F057 T032 / T042。114 上 37 个发布审批单全部 `executed`：驳回、撤回、删除致取消、审批期预览、托管应用检索这几条路径从未真跑过 | 各 tasks.md |
| CI 中间件 | F052 T104 / T302 | [052 tasks.md](./052-mcp-server-face/tasks.md) |
| 部署形态 | F054 T074 compose 形态真机启动 | [054 tasks.md](./054-app-domain-runtime/tasks.md) |
| 安全缺口 | 出站白名单开启后，systemd 形态下托管应用容器仍可经网关 IP 直连宿主上监听 0.0.0.0 的服务：`--internal` 只断默认路由，访问网关地址走 INPUT 链、不经 `DOCKER-USER`。需补宿主 INPUT 规则 | 未登记到 tasks.md |
| E2E | F054 T096 `/e2e-test` + 页面手动清单 | [054 tasks.md](./054-app-domain-runtime/tasks.md) |
| 合入发版线 | 应用工场合入发版线；116 / 105 停服执行 `publish_authorization_model_change.py` 发布含 `app` 的 FGA 模型 | [beta2-openapi-base-migration.md §6](./beta2-openapi-base-migration.md) |
| 后续版本 | F050 / F058 / F059 的 design、tasks 与实现 | — |
| 环境遗留 | 114 上 form-survey 被 2026-08-18 一张 `execute_failed` 审批实例挡住迭代发布（16251） | — |

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
| **2026-09-10** | **open_api 底座整体改接 beta2 F053**：合并 `feat/3.0.0-beta2` 与 beta1 tip 到 `feat/3.0-vibe/openapi-beta2-base`，F049 实现归档、spec / design / tasks 存档；应用工场（F053–F056）改接 beta2 鉴权管线（端点 `open_api_scope` marker + `router_rpc` 的 `verify_open_api_access`）；release-contract INV-28 按伴生 D19 修订。方案与冲突解法见 [beta2-openapi-base-migration.md](./beta2-openapi-base-migration.md)。 |
| 2026-09-16 | PRD-1 剩余功能一轮实现完毕并合入 `3.0-vibe`（`59607c4f4`）：F051 模型协议面、F052 检索门面 + MCP 面、F057 `bisheng-sdk` 由 spec 补 design + tasks 后实现；F053–F056 收尾。未勾任务只剩需 114 / CI 中间件 / 拍板的验收项。 |
| 2026-09-18 | PRD-1 二十一项逐项验收：17 项完整、3 项 PRD 与实现不一致、1 项真缺口（GOV-04 只写不读）；修复免审配置绕过 INV-34、运行期凭据不计审计、v2 filelib 18 条断言失效三项（至 `a0770eb67`）。 |
| 2026-10-08 | 本索引状态列按各 tasks.md 勾选重核；新增「当前状态」与「未结事项」两节。 |
