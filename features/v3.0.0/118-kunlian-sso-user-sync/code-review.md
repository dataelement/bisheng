# F118 规格对照代码审查与修复

- 日期：2026-11-04。
- 范围：已实现的 T001—T077、T081、T083，以及已编写但未真实运行的 T078／T079；对照 spec、design、tasks 和 verification。
- 毕昇基线 5a359d8e6；网关基线 948cce69；均在 codex/118-kunlian-sso-user-sync 工作树，包含未跟踪新增文件。没有将空的提交差异当作实现不存在，也没有把基线提交视为包含实现的交付版本。
- 方法：同一代理按 SDD 规格符合性和七维代码检查审查，按用户明确授权修复；不是独立复审或最终合入门禁。
- 结论：**六项发现已关闭；真实验证仍为 EVIDENCE_GAP / NOT_READY**。没有部署、建表、真实目录／授权操作、提交或推送。T078—T080、T082 保持未完成，79/83 不变。

## 规格／设计符合性发现

| 编号 | 级别 | 原问题与影响 | 关联契约 | 修复与当前证据 |
| --- | --- | --- | --- | --- |
| R1 | P2 | browser.py:183 主体错配分支向撤销协议传 SUBJECT_MISMATCH，而 Repository 不支持该原因。请求虽被拒绝，但预期 SQL 撤销没有发生，返回了 TRUST_REJECTED 而非 SESSION_EXPIRED | REQ-04／09；AC-17／26；T037、T045／046；design §4.5 | 复用既有 IDENTITY_CHANGED 原因。真实 HTTP＋SQLite Repository 先复现 403，修复后 401、持久会话失效、原正确 Cookie 也不能重放；E-032。没有发现该分支造成越权放行 |
| R3 | P2 | 网关只校验 return_to 路径，未拒绝已被 SPA 过滤的 token／code／state 等查询键。直接调用网关可绕过前端约束，成功 Location 回显这些参数 | REQ-09；AC-13；T055；design §6.3／6.7 | 服务器也拒绝 ar、access_token、id_token、token、t、code、state、ticket；键名先 URL 解码并统一大小写。九项参数回归先全部失败，修复后通过；E-033 |
| R5 | P2 | 后端 readiness 接受 public_origin 尾斜线；两端还可能接受浏览器会规范化的大写主机／默认端口。登记回调同样使用该值时仍可误报就绪，后续 Origin／CSRF／退出却不可用 | REQ-07／09；AC-13／25；T004／T007；design §6.6 | 后端与网关只接受可精确匹配的登记 Origin，拒绝尾斜线、空 userinfo、大写及显式默认端口。尾斜线和完整匹配回调下的规范化反例均已复现；Python／实际 Binder 回归通过，E-032／033。不在请求时自动改写登记值 |
| R6 | P2 | design §4.1／4.2 仍称八张声明表、未注册入口、均未实现；第九表仅在尾部补充，当前快照与 79/83 不一致 | design 当前快照；T083 及既有确认范围 | 更新实现状态、九表清单、已知坑和修订历史；未修改原 spec 的 26 条 AC 或已确认 D01—D08 |

R1 属于既定撤销协议接线不一致，不代表旧 Cookie 可在错配请求中直接冒充新主体。R3 拒绝凭据／协议参数的回显，不扩展站内落点范围。

## 代码质量／验证入口发现

| 编号 | 级别 | 原问题与影响 | 修复与当前证据 |
| --- | --- | --- | --- |
| R2 | P2 | Python OIDC 客户端先完整缓冲响应再判断 1 MiB，目录客户端没有大小上限；超大或持续载荷会先消耗内存 | 共享有界流式读取，OIDC 1 MiB、目录页 4 MiB，超限停止读取并 finally 关闭响应。原实现分别读取全部 8／16 个块；修复后最多读取到超限块即拒绝并关闭。E-032；网络预算仍由原 timeout 包住，不把 Content-Length 当可信边界 |
| R4 | P2 | T079 的计时从 Broker 投递之后开始，to_thread 内的投递／结果操作未受总预算约束；慢投递后仍可能被算作合格 | 总 async timeout 从首个状态查询开始包住投递和轮询；关闭隐式发布重试，Broker／结果网络另设 5 秒预算。慢投递用例先复现未拒绝，修复后明确超预算失败；E-032。已经发送的真实任务不自动取消 |

另排查了 Client 普通 401 协议探测：实际 logoutUserApi→request wrapper 已将原 Axios 错误规范化，该路径测试直接通过，**不是缺陷**。保留该回归用例，没有修改 Client 请求实现；E-034。

## 七维检查结论

| 维度 | 本轮结果 | 证据和限制 |
| --- | --- | --- |
| 边界条件 | 已修复 R2、R4、R5 | 超限／关闭、超时及配置反例可执行；真实网络容量仍待验 |
| 权限与认证 | 已修复 R1；保留既有职责 | 浏览器 Cookie-only、Origin／CSRF、内部签名、来源隔离、逐动作准入及原 F048 回归；未新增授菜单／权限兜底 |
| 并发与数据 | 本地证据通过，真实边界待执行 | SQL lease／fence、完整发布、Owner 回执、epoch 与撤销测试；SQLite 不证明 MySQL／DM8 锁和跨进程一致性 |
| 信息泄漏 | 已修复 R3；维持秘密隔离 | 内部 raw-body 签名、密文／哈希、固定响应、日志探针及回跳限制；真实外围日志仍待 T080 |
| 测试与证据 | E-032／033／034 通过 | 331 后端、75 网关、40 Client；五项真实用例跳过并保留 NOT_RUN，未计通过 |
| 分层与风格 | 本批检查通过 | 五个产品文件局部修改；SQL 仍在 Repository，Owner 仍通过 application；Ruff、逐文件守卫及前端门禁通过 |
| 文档同步 | 已修复 R6 | design／tasks／verification／运行说明已同步，spec 正文不变 |

## 需求追溯与审查范围

| 需求 | 主要审查路径 | 证据及未验边界 |
| --- | --- | --- |
| REQ-01 | 网关 Controller／OIDC／事务，后端可信交接，两 SPA 入口与落点 | E-032、E-033；Platform 复用 E-029；真实 OP／页面待 T080 |
| REQ-02 | 目录稳定绑定、User Owner fence／回执、Tenant Owner 显式成员关联 | E-032；真实双 DB 与两实例待 T078 |
| REQ-03 | 目录 list／detail、全页暂存／校验、显式映射与管理 API | E-032；真实全租户数据与 Key 范围待验 |
| REQ-04 | browser／session service、HTTP 中间件、WS message_admission、因果上下文 | E-032；真实长连接／外部失效传播待 T080 |
| REQ-05 | 发布状态／auth_epoch、人工禁用、Owner 投影及恢复 | E-032；真实锁竞争及停用恢复待 T078／079 |
| REQ-06 | Repository 原子发布／失败指针、Worker 注册和恢复、真实测试入口 | E-032；真实 Broker、DB 方言和 Worker E2E 仍待执行 |
| REQ-07 | 辅助 CSRF、本地先撤销、退票兑换、网关退出和调用者 | E-032、E-033、E-034；真实 OP 确认／取消待 T080 |
| REQ-08 | 无默认角色／菜单、源账号保护、原 F048 use 和资产归属 | E-032、E-034；真实非管理员 A／B／跨租户对照待 T079／080 |
| REQ-09 | 配置／秘密装配、HMAC／nonce、Cookie、错误、旧身份分流、回退说明 | E-032、E-033、E-034；外围日志、正式禁用／回退实测待执行 |

主要实际文件范围（B／P／C／G 路径别名沿用 tasks.md）：B/sso_sync 的 application、schemas、models、repositories、clients、kunlian_* services 与 API；User／Tenant 外部身份 Owner；HTTP 中间件、认证依赖、common/chat 与 workflow Worker 的本特性增量；G 的配置、安全链、签名器、事务、OIDC、SDK 与 Controller；共享 kunlianBrowser、两 SPA 请求／退出 API 和调用者；T078／T079 四个脚本及离线入口测试。相关既有调用者以当前工作树增量与入口合同审查，未将无关旧代码债纳入修复。

没有运行真实 MySQL／DM8、Redis／OpenFGA、OP、浏览器和生产禁用／回退；没有依赖漏洞扫描或容量验收。正式交付仍需 T078—T080 和 T082 的既定门禁，不能据本报告合并／部署或声称全部 AC 已通过。可复现命令及日志见 [verification.md](./verification.md) E-032—E-034。
