# 模型审计实现评审

日期：2026-10-14。依据当前 constitution、子项目 AGENTS、task-review/code-review 七维度与 e2e-test 双层证据。代码审查结论：开发范围 **PASS_WITH_WARNINGS**；发布门禁 **PARTIAL**，不是可直接生产启用或已合并声明。

## 范围

服务端/Platform 在既有 `feat/3.0.0-dsh-audit` 工作树，审查 `git diff HEAD` 的实际未提交修改及新增文件；当前 HEAD/merge-base=`eb41b17868dfd706b93fc4df27d8d09ed10960ee`，`origin/feat/3.0.0`=`e058f58eb8d03cf582725d31e194eeeb16fce205` 已前移47提交。`base...HEAD` 不包含本次未提交文件，不能拿空三点 diff 当作“无问题”。没有自动切分支、stash、合并或提交用户工作。

客户端独立 agent 在自己的工作树实现/验证两字段协商与安全净化。除生成共享错误码副本，没有把桌面客户端开发误放入本仓库 Recoil Client，也没有新增状态/UI库或 F048 审计资源。

## 七维度

| 维度 | 结果 | 核验范围 |
|---|---|---|
| 边界 | 通过（定向） | Unicode/UTF-8/上下文4096字节、路径/租户参数、稳定cursor、预算/超时/有限关闭、历史块读取上限 |
| 认证/范围 | 通过（代码+隔离） | UserPayload管理员入口→既有authorize_admin→历史记录tenant；超管配置/租户管理员只读；原文前 durable attempt。正式JWT/FGA/Child矩阵仍待环境验收 |
| 并发/幂等 | 通过（定向） | SQL唯一键与锁、模式版本事务、冲突不覆盖、状态版本CAS、迟到事实、Redis代次、最多100租户/请求分批、4线程12工作隔离 |
| 信息泄漏 | 通过（定向） | SQL无正文、scope HMAC而非裸文本SHA、AES-GCM+AAD/私有路径、最小模式诊断、错误仅类型、原文纯文本且no-store，无token/直链/列表预览 |
| 覆盖 | 部分 | 103项定向、22项前端、独立真实存储HTTP、真实客户端代码联调；DM8/正式UI/并发故障量化未执行，不计绿灯 |
| 风格/分层 | 修改范围通过 | Endpoint→Service→Repository，核心规则守卫/ruff/修改文件ESLint/全前端严格类型/i18n；Platform全量93既有error仍需处置 |
| 文档 | 已回写 | spec0.19不扩大范围；design0.9实际模块、tasks1.1落点/勾选、rollout/acceptance/validation及客户端文档保持证据分级 |

## 本轮发现并修复

1. 普通 MySQL DATETIME 丢子秒使连续请求排序不稳定，naive UTC 也会误显示时区：通用 `PreciseDateTime` 的 MySQL fsp=6、UTC DTO与过滤转换，真客户端严格顺序验证。
2. 大小写/尾空格 ID 被数据库 collation 合并风险：原始UTF-8摘要索引筛选、读出精确核对；不限制UUID格式、不trim。
3. 取消等待不会结束底层阻塞线程：独立有界审计executor，真正完成后才释放容量，主业务默认线程池可继续工作。
4. 原件加密但 occurrence 的裸 SHA 仍可猜测短提示词：统一改为作用域/版本 HMAC清单与引用，没有裸原文SHA列。
5. 每片重扫全量事实、深model_dump、React每片复制/渲染全量均会随长正文放大成本：增量字节计数+清单终止核验；按模型浅字段增量编码不复制嵌套树，必填 `content:null` 保留；UI ref保存和最多100帧分段浏览。
6. 调小新写块会拒绝历史大块：编码-v1读取上限固定64KiB，帧解析预算256KiB；不改变原件或退回明文。
7. 页面从单请求切会话未清过滤：重置不相关过滤，四条请求严格顺序；默认折叠且单次原文不预取。
8. 独立证据刚到达即报缺口、模式读取失败误标未知：AWAITING保护窗口/活动，DEGRADED_OFF不算缺口；没有生效模式证据只能MODE_UNKNOWN，不能用当前配置倒推。
9. 构造end帧即标查看传输完成会把未发送的end算成功：生成器被成功继续消费后才记录COMPLETED；在end处关闭保留INTERRUPTED。仍不声称客户端收到所有字节。
10. Worker一轮分派全租户可能无限扩张：最多100、稳定游标继续分派，整型tenant参数与可信header严格匹配，Beat可配置。

上述是本轮开发中修复的实现问题，不是把审计失败改成业务失败，也没有引入补报、源ID、气泡推断、安全围栏、敏感词、全文检索或自动删除。

## 未关闭的警告/门禁

- 发布线已前移；同步与再回归须在保留当前未提交工作的前提下进行，未擅自合并。全 DSH 的7个失败和全量lint93个error在干净原基线复现，未扩大到无关权限/展示名修复，也未通过suppression藏掉。
- 真DM8、正式JWT/FGA/Gateway/供应商与Electron/Fork/Windows验收缺环境，当前仅隔离角色源；不承诺生产授权已验收。
- D-09正常30请求时效报告已出；并发长流、失败/取消/模式降级分类量化、持续容量与备份恢复责任未完成。UI显示跨进程缓冲全量未知，不能宣称精确全量覆盖或零丢失。
- 新表尚未正式发布；早期原型库需差异迁移，不能依赖create_all补列。历史密钥必须保留，CONTENT启用先确认持续留存运营责任。

详情见 [validation-results.md](./validation-results.md)、[audit-acceptance.md](./audit-acceptance.md)、[audit-rollout.md](./audit-rollout.md)。不执行自动commit/push/部署/删业务数据。
