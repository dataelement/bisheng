# F118 配对交付与安全回退准备

- **结论：NOT_READY。** 本地实现和相关回归已完成 79 / 83；T078—T080 缺真实联调，T082 文档已准备但依赖未满足，保持未完成。
- 本文只形成可审查操作步骤，不执行或授权部署、建表、配置启用、真实目录同步、人工授权及会话吊销。
- 证据：[verification.md](./verification.md) E-032、E-033、E-034（Platform／三语复用 E-029）；[审查与修复](./code-review.md)已记录，真实门禁未解除；待验：[e2e-browser-checklist.md](./e2e-browser-checklist.md)。

## 配对代码状态

| 组件 | 实施工作树与分支 | 当前状态 |
| --- | --- | --- |
| 毕昇 API／Worker／两 SPA | `bisheng-kunlian-sso-planning` / `codex/f118-kunlian-sso-bisheng` | 本文所在的本地 F118 提交，基线 `5a359d8e6` |
| 商业网关 | `bisheng-gateway-kunlian-sso` / `codex/f118-kunlian-sso-gateway` | 本地提交 `55f636cbae1e71de369776204e1ca5f9166c661a`，基线 `948cce69` |

发布前需要固化配对的发布提交、制品哈希及同一配置版本，并重新核对差异和证据。当前仅登记本地提交，发布制品待生成。

## 启用前门禁（均待真实验证）

1. 闭合 EXT-01—EXT-04／ENV-01，登记受控环境和批准测试范围；明确状态传播、workspace 和租户到期语义。按实际 HTTP、SSE、WS 新动作总量验证逐次内省容量、延迟及故障关闭，不使用访问允许缓存抵消容量缺口。
2. 通过 T078 双 DB／共享 Redis／跨节点并发与故障测试；通过 T079 真实 Worker／OpenFGA API E2E 及 T080 两 SPA＋OP 验收。现有 DM8 cursor 用例未接线，不构成中央回归入口已可用的证据；需提供实际入口与结果。
3. 审查部署计划：独立九张新表（含 user_external_identity_projection）通过既有模型发现／建表流程创建，核对各 DB 字段、索引、权限和备份。不改原 User／Tenant 列，不做历史账号迁移。真实建表另获授权，不在本轮执行。
4. 后端、Worker、Beat、网关、两 SPA 作为配对版本安装时，目录／登录／网关入口默认关闭；验证旧身份通道。配置仍用已有 sso_sync.kunlian 与 custom.kunlian，不把新顶层 YAML 键直接交旧镜像。
5. 登记固定 HTTPS publicOrigin、issuer／端点／客户端／回调，确保 WS 经同一 Cookie 可达入口；专用网关直连后端，peer 网段可信，内部请求不带 Forwarded 头。核对 Host-only／Secure／HttpOnly／Lax Cookie、已知旧 Cookie 清理范围。
6. 各用途秘密独立受保护注入，校验加密密钥格式、引用、版本及跨节点一致性；不得用旧 JustAuth、旧 HMAC 或同步 Key 代替。应用、反代和观测链关闭 wiretap／敏感头与完整协议 URL 日志。依赖版本／许可证检查不等于漏洞扫描和生产安全验收。
7. 先在登录关闭、目录启用的受控阶段执行初始化；按当前 SQL policy_revision 登记更高的受控版本，使策略真正落 SQL。查询 status 验证完整目录和投影，不能以 REQUESTED／FETCHING 或 HTTP 202 当成功。修正冲突映射，仅关联已有本地租户；由管理员提前配置菜单和必要对象授权。
8. 再以更高 policy_revision 启用登录策略，观察 SQL 版本、同步／投影状态与新会话。该升版会使旧会话失效，不复活旧会话。小范围通过 A／B／跨租户验证后才讨论正式启用；本文件不批准该动作。

## 受控禁用顺序

影响对象是本连接的昆联新登录和后续访问；不会删除账号、业务资产或人工授权，其他身份仍走原合同。配置修改本身不等于控制面已生效。

1. 暂停入口引流；保持能识别昆联标记的 API／Worker 版本运行。
2. **先保留 directory_enabled=true，设置 login_enabled=false，并明确提升 policy_revision。** 经现有全局管理接口 POST /api/v1/identity-integrations/kunlian/sync 或受控 Worker 请求，将新策略提交 SQL。目录服务会先 apply_connection_policy，再登记同步需求；仅关两个开关会阻断这条落库路径。
3. 通过 GET /api/v1/identity-integrations/kunlian/status 及受控数据库核验，确认 enabled=false、policy_revision 已更新，租约失效、绑定 epoch 已推进；从另一节点用旧 Cookie 请求业务必须拒绝。同步网络失败不抹掉已提交策略，但必须核验 SQL，不能只看配置或队列投递结果。
4. SQL 失效经两节点验证后，才停止目录同步／入口；保留 connection_id 的材料清理任务可继续。硬期限即拒绝，物理密文清理依赖下一次成功调度，需观察积压和失败，不承诺零延迟擦除。
5. 已开始任务按原设计继续，不自行取消。排空登录交接及短期事务；单次退出仍应保留受限本地协议，不因 AT 到期改为业务允许。若要真实批量吊销或清理，另行审查目标和操作计划。

## 回退与恢复

- 禁止直接回退到忽略 kunlian_session／来源标记的旧后端；旧 JWT 可能被其普通认证路径接收。必须先完成上述 SQL 禁用、跨节点拒绝和会话／交接排空，保留能识别并拒绝昆联会话的兼容版本。不能据本文件承诺任意旧版本安全。
- 保留九张独立表、Owner fence／回执、账号、人工 Grant 和业务资产；不 drop 表、不合并历史账号、不把 localStorage 清理当 SQL 撤销。原表未改，无历史数据逆向迁移步骤。
- 恢复需要新的明确 policy_revision、当前目录／映射／本地资格及人工授权核验，重新授权创建新会话；不会恢复旧会话或补回已人工撤销的 Grant。已结束的远端会话不能由毕昇回滚恢复。
- 回退配置／版本前先复核密钥可读性和材料保留期限；不要在仍有未到期数据时随意换加密密钥。退出票据不是业务凭据，收到 OP 回调仅证明该次回调，不证明所有 OP 会话已结束。

## 未完成事项

T078 的两份真实存储测试、T079 的两份 API E2E 文件已补齐，运行参数及操作侧协作见 [live-test-runbook.md](./live-test-runbook.md)；真实环境尚未执行，结果为 NOT_RUN，不能将离线入口检查或跳过当作通过。T080 清单已准备，真实执行仍 BLOCKED／MANUAL_REQUIRED。T082 需上述结果、容量和外部契约全部闭合后复核，当前仍为 NOT_READY。
