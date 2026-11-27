# Token Exchange 需求草案

状态：待确认。关联需求：用户要求 A 用户登录后，经毕昇 token exchange 获取供 B 使用的令牌；已确认由毕昇签发，B 信任毕昇，输入为毕昇 OAuth Access Token。

## 用户故事

作为已登录 A 的用户，我希望经授权后访问 B，无需再次输入密码；作为平台管理员，我希望只有预先允许的 A→B 组合能够交换，且不会扩大用户授权。

## 验收标准

- AC-01：WHEN 持有有效毕昇 OAuth Access Token 的 A 按已授权组合申请 B 令牌，THE SYSTEM SHALL 签发与同一用户、租户绑定且供 B 验证的令牌。
- AC-02：WHEN A、B 或 A→B 关系未获授权或被禁用，THE SYSTEM SHALL 拒绝交换，且不签发令牌。
- AC-03：WHEN 原令牌签名、签发方、受众、类型、有效期或关联会话、用户、租户成员资格无效，THE SYSTEM SHALL 拒绝交换。
- AC-04：WHEN 申请的权限超过原用户授权、A→B 策略或 B 的允许范围，THE SYSTEM SHALL 拒绝扩大授权。
- AC-05：WHEN 交换成功，THE SYSTEM SHALL 将新令牌有效期限制在原令牌剩余有效期内；不提供独立刷新令牌。
- AC-06：WHEN 原会话被撤销、用户停用或成员资格失效，THE SYSTEM SHALL 拒绝后续交换；已签发令牌的撤销生效方式由 B 的验证模式决定。
- AC-07：WHEN 交换失败，THE SYSTEM SHALL 返回可识别的协议错误；日志和审计不得包含令牌明文、密钥或完整请求。
- AC-08：WHEN A→B 授权策略变更或撤销，THE SYSTEM SHALL 阻止后续不再允许的交换。
- AC-09：WHEN 已认证的请求方不是原令牌所属客户端 A，THE SYSTEM SHALL 拒绝交换，即使其持有该令牌；首版不支持跨客户端代为交换。
- AC-10：WHEN B 使用受众为自身且仍有效的交换令牌，THE SYSTEM SHALL 使 B 能识别同一用户和租户；B 对其他受众的令牌必须拒绝。
- AC-11：WHEN 申请任一未获允许的 scope，THE SYSTEM SHALL 整体拒绝该请求；未提交 scope 的行为及最大有效期上界待确认。
- AC-12：WHEN 无法确认会话、身份、租户或交换授权状态，THE SYSTEM SHALL 拒绝交换并返回错误，不得降级签发。

## 边界与待确认

- B 作为毕昇信任的目标，验证毕昇签名及 issuer、audience、有效期和自身业务权限；本特性不生成 B 自己签发的令牌。
- 首版仅支持经过认证的 confidential 服务端发起；公开客户端不得直接交换。
- B 可本地验签，原会话撤销后已签发的 B 令牌允许在短有效期内继续有效；新交换立即拒绝。
- A→B 必须由管理员预先批准，且不得超出用户对 A 原有的授权范围。仅持有 A 令牌本身不等于用户同意访问任意 B。
- 不涉及外部 IdP token、现有 DSH 专用模型令牌的转换，或未定义的 B 业务权限。
