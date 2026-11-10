# F008 设计审查

日期：2026-11-10。方法：仓库 `sdd-review design` 的 24 项检查、Constitution Check、三路独立范围审查。依据为 [已确认 spec](./spec.md)、[design](./design.md)、版本契约和实际源码基线 `90fa8fb953`。

结论：**LGTM，设计文档审查通过，待用户确认。** 初轮问题已修订，运行时、平台初始化、Chart/交付三组复核均明确 LGTM。本结论不等于代码或集群验收通过；本阶段没有开始业务实现、构建镜像或部署线上。

## 1. 重要问题与修订闭环

| ID | 等级 | 问题 | 设计修订 |
| --- | --- | --- | --- |
| D-01 | high | 空公钥 CM 在升级时可能覆盖 Job 产出；keep 仅防卸载 | owned CM lookup/归属校验后原样保留；派生 Job 一致 no-op，外部 CM 不接管 |
| D-02 | high | 无条件初始化 DAG 会使 Vibe 关闭后仍依赖 Manager/公钥/目录 | 按 runtime/gateway/各内置依赖列条件表，关闭时不生成专属初始化或等待 |
| D-03 | medium | 子 Chart alias、replicaCount 与 values 传递不明确 | 固定 runtime/sandbox alias、保留真实字段名，父端点/子资源调用同一命名 helper |
| D-04 | medium | 普通 Job 模板不可变，旧成功记录不能证明新目标完成 | init target/PodSpec 摘要入 Job 名；按目标完成标记、有限失败/重试，保留前代记录 |
| D-05 | medium | 迁移互斥不能依赖会被 DDL 提交释放的行锁 | 固定物理 schema scope 的持久 CAS claim；running 未确认不抢占；技术表布局版本化且排除普通 Alembic 删除 |
| D-06 | medium | OpenFGA 预置匹配模型、部分中断、正常兼容升级状态不完整 | 补七态矩阵：新建/预置/no-op/新兼容目标/显式续办/拒绝外来或不匹配；模型变更仍明确迁移 |
| D-07 | medium | 保护摘要输入/编码未定义 | 固定 scope/protection 子集和 canonical JSON 编码，提供共同测试向量，不把普通资源调值当保护断档 |
| D-08 | medium | policy 未声明总预算，仍可能由心跳自报 | 增加 execution_budget，由 Backend 期望文件核对，并与配额/并发同源 |
| D-09 | medium | Helper requests 小于 limits 时按 requests 预约会低估承诺 | 首期执行域 Helper CPU/内存 requests=limits，按真正阶段有效需求预约；控制面不受此等值约束 |
| D-10 | medium | ready/serving 仅文字分离，可能重新一律拦入口 | 明确 admission status 与持久 serving 谓词和五种状态表，诊断不参与，实际授权不续活 |
| D-11 | medium | legacy 保护连续性缺可验证输入 | 部署期前代映射精确核对 Backend 旧记录后一次登记；旧 false/unknown 永不追认 |
| D-12 | medium | 若报告与 policy 同文件，写诊断会改变策略摘要 | 独立 diagnostic CM/文件，CAS 只写报告，普通启动可无该卷；policy 原字节及冻结快照不变 |

D-05、D-06 经平台二轮复核进一步补齐 claim 的物理作用域/生命周期及同安装新目标正常升级分支，之后平台复核 LGTM。修订均为技术合同收敛，没有修改已确认 AC。

## 2. 24 项核对

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 1 目标清晰 | PASS | §1 标准交付与诊断解耦 |
| 2 非目标 | PASS | 不发行镜像、不部署、不迁移122、不装驱动/格式化、不新增模板UI |
| 3 特有约束 | PASS | §2 配对版本、冻结与信任边界 |
| 4 Constitution Check | PASS | C1 无Backend编排凭据；C2 双DB；C3/F114租户；C4生产模型仅operational；C6密钥分离/不泄漏；C8权威内容外置，其他全局法则引用原文 |
| 5 关键决策 | PASS | §3 八项决策 |
| 6 备选与理由 | PASS | 每项列被否方案与已有源码约束 |
| 7 重新考虑条件 | PASS | §3 明确对应触发条件，不预先扩展新形态 |
| 8 证据依据 | PASS | §4.1 源码耦合点、已确认需求与已复核合同 |
| 9 数据流 | PASS | §4.3 策略→冻结→执行/准入，§4.5 初始化DAG |
| 10 数据结构 | PASS | policy/心跳/摘要、前代映射、claim/marker、values字段 |
| 11 模块职责 | PASS | §4.9 做什么/不做什么 |
| 12 与实际阶段一致 | PASS | 已核实基线与拟实施目标分开，未称已经实现 |
| 13 已知坑 | PASS | §5 九项 |
| 14 坑的后果 | PASS | 每项列入口、数据、配额、TLS等后果 |
| 15 处理位置 | PASS | 对应函数/模块或目标章节 |
| 16 输出合同 | PASS | §6 内部HTTP、Python入口、文件、DB和values |
| 17 输入依赖 | PASS | §6 CNI/CSI、镜像/catalog、原Vibe合同 |
| 18 风险点 | PASS | §5/§6 及兼容/发行边界 |
| 19 测试层次 | PASS | §7 跨层配对、模板矩阵、真实验收独立 |
| 20 可操作验证 | PASS | §7 未来安装/日志命令及明确未执行状态 |
| 21 后续边界 | PASS | §8 延后范围和支持条件 |
| 22 修订历史 | PASS | 已记设计初稿/触发原因，未伪称特性完成 |
| 23 与spec一致 | PASS | 已确认26条AC及§3.1后继合同覆盖，无强制环境验收任务、无24h门槛 |
| 24 任务偏差一致性 | N/A | tasks 尚未生成；按仓库流程设计确认后先生成QA用例，再拆任务 |

## 3. 实施阶段验证要求

文档的链接、代码 fence、表格列数、AC 编号和空白可在本阶段静态校验。Job 代次/密钥三方升级、CAS 互斥、中断续办、双数据库、冻结策略与保护历史、正常入口独立性等必须在代码阶段以有意义的配对测试证明，不能用本报告替代。

兼容镜像/catalog、DM8/Linux、真实 CNI/CSI 和独立新集群证据仍是后续相应发行/部署验收前提；遵守本轮只改代码与部署文件的边界。
