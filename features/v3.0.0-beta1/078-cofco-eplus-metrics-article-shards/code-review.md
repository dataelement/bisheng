# F078 Code Review Report

**日期**：2026-10-27。**范围**：审查时 worktree 的未提交差异及新增源码/测试/文档；审查时本功能尚未提交，未以 BASE...HEAD 代替工作区审查。
**Base**：origin/feat/cofco-1028-3.0.0-beta1 @ 8ebcfdcc270fbfa1c20b100262ccd5d83844c76c。
**参照**：Spec、Design、Tasks、Constitution，采用项目 L2 七维度清单自审。

## 七维度结果

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 2 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

- **边界**：严格配置；源缺失/歧义、模板 alias、已有副本/写限制/任务拒绝；复制超时保留现场；完整指纹与 alias 后验确认。切换后的最终 metadata ack 失败归 code=5，不能当作切换前失败。
- **权限/身份**：无新增端点或授权判定；保留 F073 身份与机器人范围。Repository 保留原租户约束；维护脚本使用同部署业务 ES 与固定共享文章名，不修改订阅/权限表。
- **并发**：仅成功变更终态才生成快照，提交后输出、回滚丢弃。连接失租约和结束后不宣告存活。固定 source-UUID 备份 create 原子预留，失败方不改源；无抢占/自动续跑，切换不明不重放 remove_index。
- **信息**：稳定用户 SHA256 与原 msgid，不包含正文、答案、凭据、原用户 ID。异常仅类型，运行资料不含连接凭据；旧 BS_METRIC 保持兼容。arch-guard 敏感字符串匹配无新增。
- **测试**：正式 SQLite 事务、本机 WebSocket、可观察 ES double 覆盖关键成功与故障；真实 ES 8.12.2 覆盖具体索引/别名迁移、pipeline/routing/analysis/alias 元数据及恢复读写。证据边界见 validation.md。
- **风格/层级**：配置/日志基础设施不反向依赖业务；schemas 只读快照，infrastructure 格式化输出。无新依赖/表/API；脚本按规划/编排/CLI 拆分，Ruff 统一格式。
- **文档**：终态分类、去重/分母/窗口、过期、安全索引名、COPY_PENDING、恢复副本 pipeline 及恢复写入后回退边界与实现同步；release contract 已回写。

## 已修复问题

1. 覆盖拒绝、等待超时及恢复等终态入口；快照在既有业务事务提交后观察。
2. 关联 inbound 使用 LEFT JOIN，避免指标读取导致缺失行时静默跳过原业务异常。
3. finally 保证关闭事件；删除接管重复输出，拒绝关闭后的迟到心跳；接线与 retry 指标异常隔离。
4. 写屏障后 refresh，覆盖未刷新增删改；独立恢复副本核验后才允许移除原具体索引。
5. 复制目标关闭 default/final pipeline，正常目标恢复原策略后再次核验；手动回切备份前必须恢复 pipeline。
6. 既有连接测试等待真实认证，修正异步竞态；最终切换确认失败归待核实。

## 待环境验证（Medium）

- M1：未连接客户 E+ 或真实双 Worker/采集环境。需验证真实租约交接、群聊发送者、去重、权限与监控过期；本地 fake 租约不能替代。
- M2：未在 MySQL/DM8 和真实多节点/生产规模 ES 执行。SQLite/单节点不证明方言、配置、分配策略、容量或频道应用 API 行为；需中央/验收环境补齐。

**Overall：PASS_WITH_WARNINGS**。当前未发现必须修改的代码级缺陷；本报告不是部署/迁移授权或客户环境验收通过。
