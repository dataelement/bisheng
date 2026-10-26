# Vibe 治理收尾 · 第三轮设计评审

**结果：NEEDS_FIX；独立架构评审 REVISE。发现 1 项阻塞问题、1 项应修正问题。** 上一轮五项问题仍已在设计中关闭，本轮继续沿真实调用链发现新的遗漏；此前 LGTM 是历史评审结果，不再代表当前结论。

日期：2026-10-23。源码 HEAD `7b90271017b74f8c43075dd28e40d895462d6783`，产品代码基线 `5f2541f4bc483c24624fede9031c88c4ec6f58f4`。本轮只评审并记录发现，没有改写三份设计、规格或产品代码，没有执行测试、故障注入或远端操作。下述失败序列为静态推演，尚非真实环境复现。

## 1. B1：隔离规则丢失后，既有应用没有恢复或隔离路径

**严重性：high / blocker。关联 F054 AC-66、AC-68、AC-69。**

- 设计位置：[F054 design.md:151](../../features/v3.0.0/054-app-domain-runtime/design.md)、[同文档:155](../../features/v3.0.0/054-app-domain-runtime/design.md)、[同文档:161](../../features/v3.0.0/054-app-domain-runtime/design.md)。§4.4 的宿主 timer 是“只验证”，报告只用于新 create/claim/路由提交准入；安装更新中的失败恢复不等于运行期间持续修复。
- 失败序列：应用已运行且报告通过 → 本模块 INPUT 跳转因受控故障丢失（模拟防火墙重载）→ 应用继续运行 → verifier 报 failed → 新部署被拒绝，但既有应用仍可直连宿主监听服务。报告失效本身不会关闭数据面路径。
- 不断言普通 dockerd 重启必然删除规则，也不把防御恶意宿主 root 作为目标。缺口是已经检测到的隔离故障没有执行消费者。
- 修正方向：明确宿主 unit 在规则丢失、支持范围内的服务重启时如何恢复本模块规则、读回并配对验证；恢复不了时，明确本机隔离或停止受影响执行体的责任方、状态及恢复条件。网络隔离不等于 writer 已停止，仍须原停止证据才能交接数据卷；不能强删未知 writer。
- 定向验证方向：仅破坏专用环境的本模块 INPUT 跳转，观察已有应用的禁止连接、恢复或隔离、报告状态和重新准入；同时验证入口/egress 允许路径及无关网络。当前未执行。

## 2. S1：凭据审计补丁没有覆盖实际 binding 回收写方

**严重性：medium / should-fix。关联 F056 AC-59、F055 AC-81。**

- 设计位置：[F056 design.md:95](../../features/v3.0.0/056-app-square-governance/design.md)、[同文档:142](../../features/v3.0.0/056-app-square-governance/design.md)。D15 将具体新增落点指向 `CredentialService._audit`，但运行期 binding 的失效另有写方。
- 实际签发入口：[app_credential_service.py:186](../../src/backend/bisheng/app_publish/domain/services/app_credential_service.py) 的 `stage()` 经 CredentialService 签发候选凭据，再保存 operation binding。
- 实际回收入口：[runtime_projection_service.py:50](../../src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py) 切路由时直接把旧 binding 标成 revoked；[同文件:64](../../src/backend/bisheng/app_runtime/domain/services/runtime_projection_service.py) 在失败候选/停止终结时同样直接改 binding。两条路径均不调用 [CredentialService._audit:305](../../src/backend/bisheng/open_api/domain/services/credential_service.py)。不能把 binding 失效等同于 ApiCredential 行已撤销。
- 失败序列：正式 v1 → 发布 v2 或同版本刷新 → 新凭据签发 → 旧 binding 失效 → 按 app 查询操作审计。仅补 `_audit.target_app_id` 能找到新签发，仍没有此次旧 binding 回收事实；读取侧不能补造该事件。
- 修正方向：将真实 binding 状态变化接入凭据 Owner 的公开应用协议，说明可信 app/credential/operation 关联、事务或持久事件交接，以及重试去重。覆盖切换撤旧、候选失败、停用/删除；区分运行资格回收和 ApiCredential 撤销，避免重复记成两次同一事件。不新建并列凭据管理服务。
- 定向验证方向：切换撤旧与失败候选回收均能按 app 查到；重复 activate/terminal 不重复留痕；无状态变化不制造回收事件；关联不能来自查看者参数。当前未执行。

## 3. SDD 清单核对与边界

按 sdd-review design 的 24 项检查逐份核对，记录具体未通过项；独立 architecture-critic 按七维另审。未将新增发现反写成规格变更，也未提前拆任务或编码。

| 检查项 | F054 | F055 | F056 | 说明 |
|---|---|---|---|---|
| 1–10：目标、约束、决策、数据流及字段 | PASS | PASS | PASS | 已区分当前实现与提案 |
| 11：模块职责与生产者/消费者 | PASS | PASS | ISSUE S1 | 缺 binding 回收的真实事件生产者 |
| 12–15：现状、已知坑与落点 | PASS | PASS | PASS | 本轮源码核对未改变已有实现声明 |
| 16：Outgoing 接口与数据合同 | ISSUE B1 | PASS | ISSUE S1 | 运行期隔离失败无执行消费者；回收事件交接未闭环 |
| 17–22：依赖、风险、验证策略及历史 | PASS | PASS | PASS | 验证策略是拟执行内容，非验收通过证据 |
| 23：规格一致性 | ISSUE B1 | PASS | ISSUE S1 | 现有合同不足以兑现持续隔离和回收可查承诺 |
| 24：tasks 偏差记录一致 | PASS | PASS | PASS | 历史任务明确不代表本轮增量已交付 |

F055 的固定部署 key、owner 值更新、同 UoW 生效及日志敏感项协议本轮未发现新的独立问题。F056 完整导出、固定读视图、失权检查和重试合同保留；不能把“尚未运行”误称为已证明可用。

部署加密 key 轮换仍仅为运维说明。规格已确认；设计未确认。依据 AGENTS.md §6、SDD-Guide §3 和 sdd-review，本轮停留在设计评审，不进入任务拆解与编码。独立架构结论是建议，由用户决定下一步。

## 4. 证据与历史

- [当前三份设计全文与 AC 映射](vibe-governance-closeout-design-review-2026-10-23.html)
- [本轮独立审查原文](vibe-governance-closeout-architecture-critique-round3-2026-10-23.md)
- [上一轮修订复审（历史）](vibe-governance-closeout-design-revision2-review-2026-10-23.md)
- [上一轮独立审查原文（历史归档）](vibe-governance-closeout-architecture-critique-round2-2026-10-23.md)

本轮只做静态文档/代码核对及本地链接、HTML 目录、离线资源检查；未做页面视觉或打印实测，未跑产品测试或全量回归。三份 spec/design 的 SHA-256 及每项检查状态见同名 JSON。
