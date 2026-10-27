# 应用密钥 · 单表与用户确认重建设计评审

> **后续状态：用户已确认 F055 简化设计，任务清单已评审，现进入实施。** 下文保留设计评审时的结论与测试计划；没有据此宣称代码或E2E已完成。

**F055 设计复审：LGTM；独立架构复审：PROCEED。修订规格已获用户确认，设计仍待单独确认。** 本结论仅覆盖 F055 简化设计及必要接口衔接；F054 的宿主隔离恢复 B1、F056 的 binding 回收审计 S1 仍未关闭，三份治理设计整体不能标成全部通过。

## 1. 本次确认与当前方案

用户已明确回复：“确认修订规格，更新简化设计”。92 条 AC 的规格正文没有再改；本轮只记录确认元数据并更新正式设计。

| 环节 | 简化后的行为 |
|---|---|
| 持久配置 | 只新增一张 AppSecretConfig 表，每应用一行，整组值加密；逐项修改时间放在加密映射中 |
| 保存/删除 | 写配置、revision、既有审计；不调用 manager、不创建部署操作、不重启 |
| 页面差异 | 比较当前正式路由对应 operation 的受限冻结环境与最新配置；只返回差异名/状态 |
| 用户确认 | 显示可能短暂中断；取消不发请求；版本/config revision/route epoch 过期则拒绝 |
| 实例重建 | 复用 RuntimeOperation 与部署执行器；原版本/镜像/profile/档位/PVC不变，不审批、不构建、不迁移 |
| 失败与重放 | 沿原操作账本、期限、writer 停止证明和幂等；不自动再发重建，已保存配置不丢 |

不再新增 AppSecretState、AppSecretMutation、配置独立 applied 回执、自动配置扫描器或自动失败重试。部署加密 key 仍固定保存/备份，轮换仅运维说明。原审批声明、owner 权限、预检/预览空值、敏感输出保护保持。

## 2. 与真实底座的衔接修订

独立评审初轮找到三项衔接问题，已修订并由同一独立 agent 复核；自身 maintenance 的 epoch 变化也已补齐。这里的“关闭”表示设计合同已明确，不是源代码已修复或部署验收通过。

| 问题 | 最终设计合同 | 结果 |
|---|---|---|
| maintenance 由本操作自己推进 route_epoch，可能被当外部变化拒绝 | 既有事实到路由的精确幂等转换记在原 operation；只允许本操作的 before/after，重复旧事实不再改新路由 | 已关闭于设计 |
| 异步 accepted 后没有 HTTP 等待者提交 ready | 冻结 auto_commit=true；现有 fact 事务结束后调用提交，同事实重报仍重试原提交 | 已关闭于设计 |
| 受理锁序与 claim/fact/commit 不兼容 | 局部锁表明确 App→node/assignment→route→config；不回锁已有 operation，只操作本事务私有新行；fact/commit 两段事务 | 已关闭于设计 |
| 凭据签发/主体/审计在独立 session 中先提交 | 凭据 Owner 提供显式同 session 的 stage_in_transaction，覆盖全部 producer 和 DTO 构建；失败候选全链回滚 | 已关闭于设计 |

单表是因为运行状态已有持久账本；上述接线仍是必要的少量跨模块修改，不能宣称把旧 deploy() 原样调用即可兑现手动同版本重建。

## 3. SDD design 检查（F055）

```
LGTM
```

| # | 检查 | 结果 | 设计依据 |
|---|---|---|---|
| 1 | 目标简明 | PASS | §1 |
| 2 | 非目标明确 | PASS | §1 / §8 |
| 3 | 本功能约束 | PASS | §2 |
| 4 | Constitution Check 引用与门禁 | PASS | §2；release-contract 新资产登记 |
| 5 | 关键决策 | PASS | §3（D 编号保留） |
| 6 | 备选、选定与原因 | PASS | §3；F054 D6/D12、F055 D17–D20、F056 D12–D15 |
| 7 | 重新考虑触发条件 | PASS | 各决策末句 / §8 |
| 8 | 具体证据 | PASS | §4.1 / 下方源码证据表 |
| 9 | 主数据流 | PASS | §4.1 图与文字 |
| 10 | 字段与 JSON 契约 | PASS | §4.4①②：单表、API、comparison 与受限 DTO |
| 11 | 模块做什么 / 不做什么 | PASS | §4.3 |
| 12 | 现状与拟实现区分 | PASS | 页首 / §4.1 |
| 13 | 反直觉事实 | PASS | §5 |
| 14 | 坑的后果 | PASS | §5 表 |
| 15 | 处理文件或函数 | PASS | §4.3 / §5 |
| 16 | Outgoing HTTP/Python/数据 | PASS | §4.4③④ / §6.1：snapshot、stage、ready提交、route比较的生产消费方 |
| 17 | Incoming 服务/配置/二进制 | PASS | §6.2；现有凭据独立事务与显式session适配 |
| 18 | 依赖破坏风险 | PASS | §4.4③局部锁图、自动恢复限制、执行上下文留存；§6.2 |
| 19 | 测试层次与范围 | PASS | §7；只定向、不全量 |
| 20 | 可操作手验入口/命令/身份 | PASS | §7；真实环境尚未执行 |
| 21 | 后续边界与不做理由 | PASS | §8 |
| 22 | 修订历史 | PASS | 末节，保留旧基线引用 |
| 23 | 规格一致 / AC 追溯 | PASS | 92条AC；手动生效新增/修订追溯见统一稿55条映射 |
| 24 | tasks 偏差认知回写 | PASS | tasks状态及追加偏差同步；未展开或勾选本轮任务 |

## 4. 独立复审与未关闭事项

- [最终独立评审原文](vibe-app-secrets-manual-apply-architecture-final-2026-10-23.md)：PROCEED；七维均绿，无未决 blocker/should-fix/nit。它是设计建议，不是用户确认或实施授权。
- [初轮独立评审原文](vibe-app-secrets-manual-apply-architecture-round1-2026-10-23.md)：保留历史 REVISE 与对应源码路径，不覆盖成“从未有问题”。
- [此前三份设计第三轮结果](vibe-governance-closeout-design-round3-review-2026-10-23.md)：其中 F054 B1 与 F056 S1 尚未关闭，本轮凭据受理原子性不等于回收审计已补齐。

## 5. 仍需在编码阶段执行的定向验证

保存/删除/取消均零执行副作用；未引用与 A→B→A 不误报；快照缺失/路由变化显示未知；原确认重放和过期新请求分开；双 SQL session 交错；候选签发后 seal/flush/commit 失败回滚；maintenance重复与外部route改变；ready提交丢响应/重报；失败不自动创建下一次操作；原镜像/代码/档位/SQLite/PVC保留。Docker/K8s分别验证变化路径，不跑全量；DM8仅静态。

本轮未改产品代码、未运行产品测试或部署、未公开推送/打tag。Markdown/HTML同源、目录/链接/AC编号/节号与hash仅静态检查；视觉和打印未实测。

## 6. 正式文档与 SDD 阶段

- [F055 正式简化设计](../../features/v3.0.0/055-app-publish-pipeline/design.md)
- [已确认的修订规格](../../features/v3.0.0/055-app-publish-pipeline/spec.md)
- [三份设计全文及当前追溯](vibe-governance-closeout-design-review-2026-10-23.html)

依据 AGENTS.md §6、SDD-Guide §3 和 sdd-review，设计需要用户单独确认后才能拆任务与编码。本次规格确认已经登记，不会再次请求同一规格确认。
