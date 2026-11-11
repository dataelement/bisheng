# 历史架构复评快照

以下为实施前原设计的独立复评，保留审查证据。用户随后明确移除总标记/claim、旧迁入及额外地址状态；现行设计和问题闭环见 [design-review.md](./design-review.md) 与 [design.md](./design.md)，下文不再表示当前阻塞项。

**REVISE — 初始化完成标记未绑定完整授权目标，存在旧成功记录提前放行新版本的路径；另需补齐首次升级与旧资源准入的衔接。**

| 维度 | 评分 | 理由 |
|---|---|---|
| 1. 需求与质量属性一致性 | 🟡 | 目标、非目标和继承合同清楚；可移植安装、安全隔离、升级保真是主要属性，但没有明确排序。 |
| 2. 边界与职责 | 🟢 | Chart、Backend、Manager、Admission、一次性初始化的权限和职责总体清楚。 |
| 3. 模式克制 | 🟢 | 复用现有子 Chart、正式镜像和迁移入口，新增结构大都有具体故障或安全约束支撑。 |
| 4. 数据与状态模型 | 🔴 | 初始化目标遗漏授权模型及 Permission Catalog 身份；旧安装如何建立新 claim/完成标记也不完整。 |
| 5. 变化容忍与 YAGNI | 🟢 | 更广 CSI、PKI、持续诊断和独立基础组件包均保留为未来条件，没有提前搭建。 |
| 6. 故障与规模现实性 | 🟡 | UID、未知写入者、期限和 Job 不可变性考虑充分；升级时旧资源 Admission 的连续性尚未闭环。 |
| 7. 决策记录与可读性 | 🟢 | 主要决策有理由、否决方案和重新考虑条件，实施入口也明确。 |

### Blocker

**B1 — 初始化目标没有覆盖被初始化的授权状态。**
**维度：4、6。** 锚点：`design.md:171–172、186–188、194–206`。`init_target_digest` 包含 schema heads、官方运行环境 catalog 和初始化合同版本，却没有明确包含预期 OpenFGA Store/model checksum、Permission Catalog 合同或已认可 pin；完成标记同样没有这些字段。`wait-schema` 仅检查 schema 与匹配的成功标记。

因此，授权模型代码变化而 schema heads/运行环境 catalog 未变时，新 bootstrap Job 会因镜像变化获得新名字，但旧成功标记仍可能满足新 Pod 的等待条件。新 Pod 可在新 Job 验证授权状态之前启动，甚至在该 Job 失败时继续启动。保留 lifespan 无法保证修复这一点：现有 `src/backend/bisheng/core/openfga/manager.py:69–113` 明确允许发现前代模型后启动 API/worker，同时令权限运行时不可用。

**建议方向：** 将预期授权模型与 Permission Catalog 合同、目标 Store 归属纳入初始化目标，并记录经验证的实际 pin；或者明确规定并强制执行覆盖这些变化的合同版本递增。等待者应消费同一完整目标，不能仅凭 schema/profile 标记放行。

### Should-fix

**S1 — 首次升级到新 bootstrap 协议的接受路径缺失。**
**维度：1、4。** 锚点：`design.md:188–204`。现有 SQL 的接受条件是“CURRENT/模型/目标摘要匹配”，正常升级则要求同安装的前代 claim 已成功；但 `deployment_bootstrap_claim`、安装目标摘要和完成标记都是本设计新增内容。现有公开 Chart 与 `src/backend/entrypoint.sh` 只有原 Alembic 启动流程，不产生这些记录。§4.4 的 legacy 保护映射也不建立数据库初始化归属。

一个授权状态健康、已有用户默认项的旧安装因此没有明确的可接受状态。将其归为“无法确认归属”而拒绝，不能兑现规格中的升级保留合同；排除 122 整并也没有排除其他正常旧安装升级。

**建议方向：** 明确支持的首个升级基线，以及验证现有 schema、授权 pin、数据归属后建立初始 claim/标记的受控接纳流程；若只支持本特性产生的后续 release，应明确收窄并重新确认规格。

**S2 — Backend 接受前代保护历史，没有对应 Admission 的旧资源接受规则。**
**维度：4、6。** 锚点：`design.md:130、139–159`。设计规定旧 UID 按稳定基线处理，并在 Backend 登记前代→目标映射；但未说明该已认可映射如何成为 Admission 的受信输入。

现有 `src/runtime-manager/runtime_manager/k8s_admission.py:378–379、435–436、521–535、599` 的 PVC binding、CNI、status 和删除判定使用单一当前 `self.revision`。当认可的连续升级改变 revision、旧 Pod/PVC 保留旧 annotation 时，Backend 保存 true 历史仍不能让新 Admission 接受旧资源的真实终止与绑定更新。

**建议方向：** 明确前代规则的生产者、分发对象和 Admission 本地消费方式，并限定到认可作用域/旧 UID；保持 status 路径不依赖 Backend，同时避免把任意旧 revision 永久加入允许列表。

**总结：架构方向合理，先补齐完整初始化目标和两条升级状态链，再进入实现。**
