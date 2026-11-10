# Vibe 治理收尾 · 修订后设计复审

> **历史结果：本报告记录上一轮 LGTM，当前第三轮已发现新问题，见[最新评审](vibe-governance-closeout-design-round3-review-2026-10-23.md)。**

**结果：LGTM；独立架构审查 PROCEED。五项原问题已关闭，无未解决 high/medium。设计仍待用户单独确认。**

日期：2026-10-23。代码基线 `7b90271017b74f8c43075dd28e40d895462d6783`；当前设计以本报告 JSON 的逐文件 SHA-256 为准。本轮只更新设计与评审文档，未开始增量编码或任务拆解，未运行产品测试/部署。

## 1. 用户确认的范围

部署加密密钥 `runtime_payload_key` 的更换仅为运维说明：固定保存、与加密数据备份、不能直接替换；不提供轮换 UI、自动任务、迁移工具或新的 key 版本产品。owner 修改第三方应用密钥并让实例生效，仍属于本轮。真实值只进入已批准 formal 实例，预检/审批预览为空值，保持已确认规格。

## 2. 五项问题闭环

| 原问题 | 修订落点 | 处理结果 |
|---|---|---|
| R1 | F056 §2 / D13 / D14 / §4.4 | 已关闭：完整导出不设行数/90 天上限，批次只限制内存；后台一次读取视图，失败 attempt 从头只读重建、ready 后产物固定。 |
| R2 | F054 D7 / §4.4① | 已关闭：在原授权顺序之后显示已确认的“本环境配置不完整，请联系平台管理员”；正式/预览同源，不向无权者泄漏配置/对象。 |
| R3 | F055 §4.4④ / §7 | 已关闭：批准声明 → operation 敏感名 → 原执行值集合；Docker/K8s/legacy/失败与 backend diagnostic 落库都消费；短值、普通名、多行/分块、先脱敏后截断有合同。 |
| R4 | F055 D17 / §8 | 已关闭：按用户澄清关闭为运维边界：部署 key 固定保存/备份、误改拒绝，不新增轮换功能；不再承诺重加密即可换 key，历史 HMAC 由固定 key 维持。 |
| R5 | F055 §4.4③ / §7 | 已关闭：选定同一 AsyncSession/UoW 原子提交 route/instance/applied/receipt；响应丢失、serving/completed 重试、部分事实修复与旧 revision 拒绝均明确。 |

## 3. 复审结果与证据

使用 sdd-review design 的 24 项清单复核三份设计（共 72 项），并由未参与修订的独立 architecture-critic agent 只读核对七个架构维度。独立报告原文：[architecture-critique.md](vibe-governance-closeout-architecture-critique-round2-2026-10-23.md)。它是评审建议，不是用户设计确认；仓库 SDD 仍要求确认后才能拆任务/编码。

```
LGTM
```

三份 spec 的正文与已确认版本一致；没有用改写 AC 来消除设计偏差。上一轮 NEEDS_FIX 及独立报告保留历史，不能把本次文档复审当作原问题已经有产品代码修复或 E2E 通过。

| # | 检查 | F054 | F055 | F056 | 设计证据 |
|---|---|---|---|---|---|
| 1 | 目标简明 | PASS | PASS | PASS | §1 |
| 2 | 非目标明确 | PASS | PASS | PASS | §1 / §8 |
| 3 | 本功能约束 | PASS | PASS | PASS | §2 |
| 4 | Constitution Check 引用与门禁 | PASS | PASS | PASS | §2；release-contract 新资产登记 |
| 5 | 关键决策 | PASS | PASS | PASS | §3（D 编号保留） |
| 6 | 备选、选定与原因 | PASS | PASS | PASS | §3；F054 D6/D12、F055 D17–D20、F056 D12–D15 |
| 7 | 重新考虑触发条件 | PASS | PASS | PASS | 各决策末句 / §8 |
| 8 | 具体证据 | PASS | PASS | PASS | §4.1 / 下方源码证据表 |
| 9 | 主数据流 | PASS | PASS | PASS | §4.1 图与文字 |
| 10 | 字段与 JSON 契约 | PASS | PASS | PASS | §4.4 |
| 11 | 模块做什么 / 不做什么 | PASS | PASS | PASS | §4.3 |
| 12 | 现状与拟实现区分 | PASS | PASS | PASS | 页首 / §4.1 |
| 13 | 反直觉事实 | PASS | PASS | PASS | §5 |
| 14 | 坑的后果 | PASS | PASS | PASS | §5 表 |
| 15 | 处理文件或函数 | PASS | PASS | PASS | §4.3 / §5 |
| 16 | Outgoing HTTP/Python/数据 | PASS | PASS | PASS | §4.4 / §6.1 |
| 17 | Incoming 服务/配置/二进制 | PASS | PASS | PASS | §6.2；F055 执行敏感项/固定 key，F056 source streaming、私有对象与 worker |
| 18 | 依赖破坏风险 | PASS | PASS | PASS | §6.2；同一 UoW 会话、驱动缓冲/固定读视图、旧执行上下文、配置误改拒绝 |
| 19 | 测试层次与范围 | PASS | PASS | PASS | §7；只定向、不全量 |
| 20 | 可操作手验入口/命令/身份 | PASS | PASS | PASS | §7；真实环境尚未执行 |
| 21 | 后续边界与不做理由 | PASS | PASS | PASS | §8 |
| 22 | 修订历史 | PASS | PASS | PASS | 末节，保留旧基线引用 |
| 23 | 规格一致 / AC 追溯 | PASS | PASS | PASS | 52 条 AC 追溯；R1/R2 不改 spec，R4 按用户运维边界处理 |
| 24 | tasks 偏差认知回写 | PASS | PASS | PASS | 当前基线覆盖历史过期叙述；旧任务状态限定为历史，增量尚未拆任务 |

## 4. 还需要在实现阶段验证的事项

本次审查确认设计合同可进入用户确认，不宣称代码或环境已经验证：

- 同事务回滚、提交后响应丢失、旧 revision、终态清理与 guard 释放的定向配对验证。
- 短值/普通名、多行/分块、历史执行值、缺失上下文安全省略，覆盖所有日志/诊断出口。
- 大于 10,000 行和 90 天范围完整导出，驱动实际缓冲、只读视图内存/连接成本；失权、崩溃重试和 ready TTL。DM8 仍按已确认边界仅静态核查，不声称 DM8 真测。
- INPUT/FORWARD 与 OBO 的已有安全收尾定向 E2E；不重跑不相关全量回归。ARM、完整离线安装、正式镜像发行仍保留在原待办。

## 5. 文档检查与 SDD 状态

Markdown/HTML 同源生成，规格 AC、目录、52 条追溯、同源设计 hash、本地链接与离线资源做静态检查。HTML 含目录、对比表、三份设计全文和离线流程图；页面视觉/打印实测未执行（此前浏览器策略拒绝 file 协议，本轮不绕过）。

下一步是用户单独确认修订设计，之后才拆增量任务并实施。旧任务未提前勾选，未新增轮换功能，未做远端或公开发行操作。
