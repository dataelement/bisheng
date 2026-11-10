# 审计验收与 AC 追溯

日期：2026-10-14。整体 **PARTIAL**：下表“通过”仅表示定向/隔离功能证据，不等同生产、DM8 或正式客户端 UI 验收。[完整结果](./validation-results.md)给出命令、基线失败、实际环境及未执行项。

## 1 双端可复核样本

客户端会话：`local-audit-04c679a9-b335-4a41-94e7-6ffa794a83c2`，认证 tenant=2、user=20。按服务端开始时间和编号返回以下顺序，客户端断言的是序列，不是 sort 后集合：

| 顺序 | 种类 | 服务端 request_id |
|---:|---|---|
| 1 | chat | `87340b39-5d1a-45c5-93f3-6142a384e23a` |
| 2 | chat，含第一轮历史 | `7eed3bbe-4ccb-44aa-87b4-458c7f25dd8a` |
| 3 | compaction | `63bd3992-076d-442b-9b01-1044546be546` |
| 4 | session-title | `baa7aa53-d7e5-4a5c-8ad2-508c1931a0bc` |
| 独立未关联 | 无 ID | `1d80bb3d-ef22-4b8a-a5cc-bc2b5fea9cbb` |

大写会话 ID 探针：`dea924db-4dc5-4dca-963f-d89fde1e6182`；尾部空格 ID 探针：`f8e12437-cd4e-481f-8720-1c971dd8ea68`。各仅查出自己一条，不混入上述四卡。核心五次无重放，另两个探针总计七次；调用期间 config_reads=0。全部 CONTENT COMPLETE，NDJSON 连续 seq/end COMPLETED，模型原文没有 audit_context 或传输 token。

这是实际客户端代码链路到真实 MySQL/Redis/MinIO，不是静态示例，但身份/上游合成，不是实际 Electron 窗口。[客户端证据](/Users/zhangguoqing/works/bisheng-work/.worktrees/feat-3.0.0-dsh-audit/docs/dsh-model-audit-validation.md)记录候选代码、类型/构建/测试与未执行场景。合成 token 不写入本文。

## 2 AC 对应证据

下列文件均在 `src/backend/test/dsh`；UI 指 Platform `ModelAuditPanel.test.tsx`、`dshModelAudit.test.ts` 和实际页面观察。“场景部分”不是将业务要求从规格删除。

| AC-ID | 已执行的证据 | 状态/限制 |
|---|---|---|
| AC-01 | contract/codec/flow；无 ID、大写/尾空格独立探针 | 隔离通过 |
| AC-02 | scope 编码、真实客户端四次同 ID、重开/重启客户端自动化 | 隔离通过；正式重登录 UI 未执行 |
| AC-03 | flow 的无 ID 健康留存及真实客户端第五次 | 隔离通过 |
| AC-04 | writer 跨用户/租户 scope；HTTP 普通/越权拒绝 | 隔离通过；正式 FGA 矩阵待执行 |
| AC-05 | 请求编号/keyset同时间稳定排序、独立物理请求 | 场景部分：并行 Agent UI/跨节点因果不在本机验收 |
| AC-06 | writer 重复正文对象复用，仅同用户/会话；codec 的 REQUEST/CONVERSATION 同值区分 | 隔离通过 |
| AC-07 | 真实客户端压缩调用独立卡片，输入原件忠实保留 | 隔离通过 |
| AC-08 | 原件按每次输入存储，无 source/revision/edge；不同 ID 独立 | 场景部分：实际 Fork/编辑/重新生成 UI 待执行 |
| AC-09 | capture/writer 缺尾片、预算满、缺清单和部分标记 | 定向通过 |
| AC-10 | flow 的流/非流工具、图片、reasoning、工具结果逐项原文核对 | 隔离通过 |
| AC-11 | flow METADATA 记录+无正文、独立状态/用量 | 隔离通过 |
| AC-12 | capture/writer/flow 连续增量及清单，真实客户端 NDJSON | 隔离通过 |
| AC-13 | flow 的调用前关闭/调用后取消/失败/ASGI中断，runtime 迟到恢复 | 定向通过；真实进程故障压力待执行 |
| AC-14 | flow inline image + codec 非文本有效载荷 | 隔离通过；不解析附件引用目标 |
| AC-15 | flow 成功模型+结算不确定+SSE错误，不重放；request_id 测试 | 定向通过 |
| AC-16 | 相同 request_id 的既有 dsh_model_call 事实引用；未知不填零 | 隔离通过 |
| AC-17 | bounded queue/executor、存储故障、全失写不改模型成功 | 定向通过；不承诺零损失 |
| AC-18 | setting/flow/admin_runtime/HTTP 的角色与范围配对；元数据无正文 | 隔离通过；正式 JWT/Child/FGA 待执行 |
| AC-19 | 逐次两类管理员 body-access、durable log 故障无正文、访问记录 | 隔离通过 |
| AC-20 | writer 同 scope 多请求保留 occurrences；无删除/过期路径 | 定向通过 |
| AC-21 | flow/keyset、cursor过滤绑定、UTC/精确 ID、真实四卡顺序 | 隔离通过；用户名真实用户目录待正式集成 |
| AC-22 | OFF/读取超时、最小诊断、非法扩展软降级，旧契约回归 | 定向通过 |
| AC-23 | request_id/flow 未迭代无 entered、既有模型权限/参数前置拒绝 | 定向通过 |
| AC-24 | runtime/flow AWAITING、CONFIRMED、DEGRADED_OFF、MODE_UNKNOWN；积压全量未知提示 | 定向通过；窗口数值待压力校准 |
| AC-25 | 真实 adapter 观察输入/输出，失败/取消事实；不称 SDK wire audit | 隔离通过 |
| AC-26 | flow token-like prompt 忠实保存、传输身份不入原文；编码/存储/日志审查 | 隔离通过 |
| AC-27 | 同上游三模式30次正常小样本、队列/线程池功能故障测试 | **部分**：并发长流量化未执行 |
| AC-28 | 专用路由含新/旧/无关联/辅助请求，真实客户端五次无重放 | 隔离通过；正式并行 Agent UI 待执行 |
| AC-29 | setting 版本/幂等/留痕事务/超管配置；只读租户管理控件 | 隔离通过 |
| AC-30 | 独立30次 entered 分母、20元数据/10完整CONTENT，固定持久Token基线 | **部分**：失败/取消/降级分类量化未完成 |
| AC-31 | runtime 最小 MODE_READ_FAILED、bounded read OFF、DEGRADED_OFF 区分 | 定向通过 |
| AC-32 | 重复历史第二轮仍单卡，四次实际调用四卡，单请求按需原文 | UI/隔离通过 |
| AC-33 | keyset分页、默认无原文、单展开/收起/切页、1000 frames分段只读一次 | 组件/桌面页面通过；窄屏未完成 |
| AC-34 | 能力子集/坏扩展/无种类/无 ID；旧 config 无扩展继续 | 双端定向通过 |
| AC-35 | 流/非流 METADATA/CONTENT，真实 SQL/MinIO健康完整，无 ID | 隔离通过 |
| AC-36 | 同源响应/用量/审计编号，上游/结算失败与前置拒绝不重放 | 定向+客户端通过 |
| AC-37 | 无 token 也刷新、代次/迟到 set/finish、独立 Redis 连接观察、超窗 UNKNOWN、迟到恢复 | 定向+真Redis通过；实际宕机/长流压力待执行 |
| AC-38 | 缺最后块/缺清单不完整、迟到补齐可恢复、冲突不覆盖 | 定向通过 |

## 3 页面验收清单

- [x] 默认列表只显示元数据和四轴，METADATA 原文按钮不可用，不预取 body-access。
- [x] 精确输入客户端第二轮 request_id，只见一张卡；明确点击原文后才读取，完整历史/实际输出显示为安全文本。
- [x] 点击“查看本用户会话”清除请求过滤，按聊天/聊天/压缩/标题四次顺序显示；原文折叠，重复历史不铺新气泡。
- [x] 状态/Token 引用/UTF-8 原文完成；截图保留为本机验收附件（临时 `/private/tmp/dsh-audit-final-proof.jpg`，不是生产页面；截图对应上一轮同结构样本，最新复跑编号见上表）。
- [x] 组件验证长会话翻页/原文清空、1000帧分段、HTML仅文本、租户管理员模式只读、证据不足提示。模式版本冲突重读由实现审查与服务事务测试覆盖，未单列 UI 冲突自动化。
- [ ] 正式 Platform 登录/租户管理员/受限 Root Child 权限矩阵，不使用 fixture presentation 替代。
- [ ] 正式 Electron 同会话续接、Fork、编辑、压缩、并行 Agent 与真实供应商/Gateway。
- [ ] Linux DM8、真实进程退出/跨节点长流、并发压力与容量持续增长。
- [ ] 375px 窄屏/信创浏览器/Windows。viewport 工具不可达，不标绿；没有为此更改用户网络或安全设置。

删除/到期功能不属于本期，不用“以后删掉”解释本次容量风险。测试数据仅由独立 fixture 拥有，结束后容器/卷整体清理，不删除任何业务数据。
