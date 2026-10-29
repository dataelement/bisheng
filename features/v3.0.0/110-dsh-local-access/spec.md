# DSH 本地登录与部门额度

关联需求：[已确认技术方案](../../../docs/dsh-seat-removal-impact.md)。所属版本：v3.0.0。
用户于 2026-10-20 明确要求按方案实施；需求发现和设计确认以该方案及本轮指令为准。

## 验收标准

- AC-01 — WHEN Gateway 未部署且未配置 Gateway HMAC，THE SYSTEM SHALL 允许有效平台自然人通过浏览器确认与 PKCE 登录 DSH。
- AC-02 — WHEN 用户刷新、退出或撤销设备，THE SYSTEM SHALL 原子轮换或撤销本地会话凭证，拒绝过期及重放凭证。
- AC-03 — IF 账号或租户无效、身份伪造或跨租户访问，THE SYSTEM SHALL 拒绝请求，且普通 JWT/PAT/SAK 不能冒充 DSH。
- AC-04 — WHEN 保存模型授权或新增用户，THE SYSTEM SHALL 不检查商业 License、人数或预分配席位。
- AC-05 — WHEN 人员有对应模型的个人配置，THE SYSTEM SHALL 使用个人额度，即使低于部门；没有个人配置则继承部门。
- AC-06 — WHEN 部门配置额度，THE SYSTEM SHALL 按成员、模型和月份独立计量，且额度来源变动不重置已用量。
- AC-07 — WHEN 个人显式额度为零，THE SYSTEM SHALL 拒绝该模型；取消个人配置则恢复部门继承。
- AC-08 — THE SYSTEM SHALL 保留模型正文、父子会话、标题、历史查询和审计密钥能力。
- AC-09 — THE SYSTEM SHALL 保留历史用量及事件读取，且新调用无需席位字段。
- AC-10 — THE SYSTEM SHALL 移除席位和商业授权页面、后台远程验席、资料同步及 Gateway 配置依赖。
- AC-11 — WHEN 旧客户端重新登录，THE SYSTEM SHALL 通过 Python 兼容路由提供相同响应契约。
- AC-12 — WHEN 已准入的模型调用失败，THE SYSTEM SHALL 在审计详情显示可确认的上游 HTTP 状态、超时或连接失败原因；不展示凭据、上游原始报文或推测历史原因。
- AC-13 — WHEN 响应返回错误或传输中断，THE SYSTEM SHALL 独立记录响应阶段可观察的原因；模型结果、用量和正文完整性保持各自事实。
- AC-14 — WHEN 查看原文，THE SYSTEM SHALL 默认完整倒序展示消息，先排序再分页；不反转单条消息的文本和工具参数片段，不过滤压缩上下文或历史消息。

## 边界

多部门及祖先部门沿用现有同模型取最大值；个人始终优先。角色历史在发布前按运维计划迁移，不能抬高已有个人额度。本次不迁移 Gateway 自有 SSO 等独立商业功能，不部署；按用户后续授权提交并推送功能分支。
