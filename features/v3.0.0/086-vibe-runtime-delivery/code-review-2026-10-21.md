# F086 Code Review Report

**Overall: NEEDS_FIX（部署验收门未满足）**

同一代理按 code-review 七维自审；没有独立代理评审；已完成Docker主链路与双架构原生容器验证，仍有交付门未完成。此结论不等于目前已有静态缺陷尚未修复。

## 范围

- 工作树：`codex/086-vibe-runtime-delivery`，代码基线 `origin/feat/3.0.0-vibe@4aa9ce69b2830b81162fe631b9c801057c40ee8b`。
- 记录的 main 参照：`origin/main@4218ba7c138a90764a304681c3d8a5875b2c9c1a`；本轮只审F086相对既有Vibe基线的修改及新增文件，不将已有Vibe差异冒充本次新代码或声称已经合并最新main。
- 真实接口/存储/Owner边界、默认应用包/镜像、CLI、独立代理、Compose/镜像CI、维护工具及文档；不扩张K8s、商业授权或新的管理页面。

## 七维汇总

| Dimension | High | Medium | 结论 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 已核查hash/尺寸/安全解包、端口、启动、依赖锁、deadline、错误信封与故障阶段 |
| 权限与认证 | 0 | 0 | scoped HMAC/持久nonce、natural-owner矩阵、SDK范围句柄及原F048/F049入口；Docker自然人/SAK主链路已验，跨租户部署及六项live权限现已通过 |
| 并发安全 | 0 | 0 | Repository UoW/节点行锁/唯一键/savepoint、当前归属、ready事务、单写SQLite；MySQL强制同步竞争通过；DM8模型静态通过，实测按用户确认留中央回归 |
| 信息泄漏 | 0 | 0 | 服务身份分离、SQL sealed_env、预检无正式凭据、包源与diagnostic脱敏、MinIO私有桶 |
| 测试覆盖 | 2 | 0 | 本地及双原生容器通过；Docker主链路/MySQL已验，剩余门见H1/H2 |
| 代码风格 | 0 | 1 | 变更Python门通过；全量前端lint的既有失败仍是合入门 |
| 文档同步 | 0 | 0 | design/tasks/接口/表/安装配置及未验范围已同步 |

## 未关闭交付门

### HIGH H1：完整离线平台交付

七个镜像已在amd64/arm64原生构建；Python/Node/static禁网、实际缓存、SQLite helper/备份、Node安装钩子/前端编译及CPython C扩展离线构建/失效通过。109完整CLI/SAK主链路、owner补包、SDK、HTTP/WS、恢复/删除及基础故障已通过。GitHub双原生工作流已在测试Tag v3.0.0-test-vibe通过，服务索引与目录已发布，109公开服务镜像启动检查通过；标签拒绝分支本地验证通过。完整离线平台安装及目录导入仍未演练。T053已关闭，详细证据见[live-validation.md](./live-validation.md)。

### HIGH H2：剩余数据库与故障/升级验收

真实MySQL五项同步竞争通过。2026-10-21修复多租户启动上下文并完成普通owner跨租户旅程、六项live权限、安装/编译/探活关键故障、快照确认故障、DDL后启动失败、长连接硬期限和真实存量升级/导入前回退。DM8按用户要求暂缓实测、模型静态审查通过，不再等待schema；Engine build停止不确定、节点失联、上传ACK丢失等完整组合及完整离线新装仍未完成。对应T055、T056；不得将代表性故障冒充所有阶段穷举。

### MEDIUM M1：既有质量门

backend两项 `test_grant_subjects_five_endpoints_accept_app` 的permission_runtime初始化失败已在4aa9ce69基线复现（2失败/3通过）。frontend lint为95错误/1警告，基线与本分支归一化日志完全相同；冻结依赖后的typecheck及i18n通过。本轮不批量改动无关页面或抹去基线失败；合入/发行前需要维护线处理或明确既有门的处置。

## 自审发现及修复记录

| 风险 | 当前处理与本地证据 |
| --- | --- |
| 可用服务身份提交通用执行载荷 | 移除无生产调用方的POST internal/operations；只允许backend业务入口建意图；候选最终提交核对批准/current/pending/冻结delivery |
| 数据路径和Engine控制可达面过大 | 单应用挂载的禁网数据helper；SQLite侧文件链接校验；独立runtime-control网络，Compose合同通过 |
| 旧版本/同版本重建句柄复活 | credential/storage/egress按当前route operation绑定；候选staged和失败清理；TTL硬失效 |
| 容器时区导致策略已过期 | UTC epoch与旧preview datetime转换；TZ=Asia/Shanghai合同回归 |
| 历史记录截断新操作、幂等错误破坏事务 | node plan先SQL过滤、控制查询不截断；唯一竞争savepoint及准入回滚测试 |
| 联网钩子取得包源凭据、补包污染原源码 | 仅受控下载阶段有源凭据；安装/build禁网，输入限制、临时副本和离线材料完整性测试 |
| 旧Engine build中断后过早释放 | started/finished持久标记；未知保持预占，完整结束后复用；离线缺基础镜像不让daemon隐式拉取 |
| 导出/快照删除留下副本 | 孤儿data-jobs按期限回收、保护活动helper/生产库；删除注册快照同时清理其传输块 |
| 清理后丢失具体依赖错误 | 有界脱敏诊断写SQL，7天后下一轮对账清尾部，控制事实保留 |

## 继续条件

代码已可评审。Docker专用平台与代理已用于验收；按已确认的DM8静态审查口径及正式发行条件，继续执行 [E2E清单](./e2e-checklist.md)。不得将skip或CI源码当成通过，不进入merge。完整本地统计见 [validation.json](./validation.json)，安装和离线流程见 [OPERATIONS.md](../../../src/runtime-manager/OPERATIONS.md)。

## 真实部署复审（2026-10-20）

已修复：MySQL重复键共享当前读、首次归属节点锁、data helper日志时间戳、HTTPS源/Node CA、容量并发采样、16121错误映射、owner恢复fence读取、预检错误详情/实际阶段及CI前置。对应真实失败和复测证据见live-validation.md。当前没有遗留的已确认F086静态缺陷；上述运行门未关闭，不能标LGTM或合并。

## 2026-10-21增量七维自审

按code-review同一代理逐项复核六个实现/测试文件：边界（非法租户ID）、权限（仅绑定可信tenant、不授予授权）、并发（ContextVar嵌套/异常/async任务隔离）、信息泄漏（无新增凭据/接口）、测试（修复前失败/修复后56通过及真实MT旅程）、风格（Ruff/arch-guard）、设计/任务同步均通过。新增静态HIGH/MEDIUM为0；完整Feature仍因H1/H2及M1保持NEEDS_FIX，不改为可合并。没有独立代理或外部评审；用户没有要求本轮再次提交。证据见[live-validation §8](./live-validation.md#8-2026-10-21多租户修复故障及存量升级)。

## 模型审查与验收口径补充

用户2026-10-21确认DM8不做真实测试，当前按模型/约束静态审查。复核15表发现2GiB/10GiB范围与INTEGER不匹配，已改BIGINT并加DDL-only扩容revision及守卫测试；28项回归通过，迁移图单head。静态问题已修复；真实DM8验证交中央回归，不再阻塞当前Feature。新增迁移未实际执行数据库升级；审查不把之前旧schema E2E当新revision实测。后续测试发行已实际通过GitHub与仓库索引核验，T053关闭；仍缺完整离线安装及平台目录导入。详见[审查结果](./model-review.md)。
