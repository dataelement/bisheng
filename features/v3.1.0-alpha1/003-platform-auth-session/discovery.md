# 需求确认记录：平台统一认证与会话

日期：2026-11-27。来源：本次用户对话，不存在另一份上游 PRD。

## 已由用户确认

| ID | 确认内容 |
| --- | --- |
| U-01 | 采用“将 DSH 会话机制平台化”，不按新增终端各建一套机制。 |
| U-02 | 网页、手机先统一为平台 Token；DSH 是毕昇自有客户端，后续版本兼容迁入同一流程。 |
| U-03 | 默认 30 天明确指 Access Token 本身，另配 Refresh Token 支持续期。 |
| U-04 | 普通旧网页 Token 不需要兼容，发布后允许用户重新登录。 |
| U-05 | 网关不签发 Token：认证成功后调用毕昇后端；本次不改网关。 |
| U-06 | 第三方应用保留已有 OAuth2／OIDC SSO 流程，不按自有客户端处理。 |
| U-07 | 本轮仅整理 spec 和 design，明确默认期限、接口与 DSH 兼容边界，不写实现。 |
| U-10 | 用户明确真实集成测试由其自行处理，本轮完成开发和单元测试；双DB、真实网关、安装包与真机验收移交用户执行。 |
| U-09 | 用户随后授权按tasks实施与测试，仅修改bisheng和bisheng-mobile；毕昇在alpha1，手机从main新建fix/mobile-session-refresh；网关及桌面保持不变。 |
| U-08 | 用户随后确认Session和Refresh Token默认90天，并确认spec S1与design D1；授权继续整理测试用例和tasks，仍不写实现。 |

## 已确认的设计决定（原草案建议，2026-11-27随spec/design确认）

| ID | 建议 | 理由 |
| --- | --- | --- |
| D-01 | Session 默认闲置 90 天；当前 Refresh Token 默认同日到期；默认不额外设绝对总寿命。 | 与已确定的 30 天 Access Token 分开，允许错过 Access 到期前刷新后仍恢复登录；不是沿用旧手机 180 天上限。 |
| D-02 | 只有服务端声明的业务活动顺延 Session 90 天；刷新、心跳和状态轮询不顺延。 | 沿用 DSH 将业务活跃与换证分开的机制，避免后台刷新单独保活。 |
| D-03 | 新平台凭证采用通用类型和签名用途；保留旧 DSH 验证器、数据和协议适配。 | 当前 DSH 限定专用 audience、固定字段及最长 600 秒，不能直接用于平台 30 天 Token。 |
| D-04 | 保留网关响应中的 `user_id/leaf_tenant_id/token`，网页落地后使用新平台会话完成一次受限的刷新 Cookie 绑定。 | 现有网关契约只交付一个 Token，不能假设它会转发新增 Refresh Token 或 Set-Cookie。 |
| D-05 | 网页和手机认证切换协调发版；旧手机无感会话迁移不在首期承诺内，必须显式公布最低客户端版本。 | 历史手机 JWT 与网页 JWT 可能无法区分来源，不能承诺只拒绝旧网页、却自动保留所有旧手机凭证。 |

## 文档阶段

- 用户已确认方向、spec S1、design D1及D-01～D-05。之后已授权实现与测试，当前进入实施阶段。
- spec的What以U-01～U-10为依据；design区分基线事实、已实现行为和用户接手的真实验收。
- 文档阶段已结束；实施基线、环境限制与分支记录见[integration-baseline.md](./integration-baseline.md)。

## 证据基线

| 仓库 | 引用与提交 |
| --- | --- |
| bisheng | `origin/feat/3.1.0-alpha1` / `572d5ecf77f7b21cd0cb0d7ab3513e5cdf9cd64b` |
| bisheng-mobile | `origin/main` / `6990f73fe10c41fb0e7171d822605fd1028d746f` |
| bisheng-work（远端仓库 bisheng-desktop） | `origin/main` / `a7a982cf1804549fc6347284c965ddb49e97916e` |

核实方式：只读 fetch、源码与路由追踪；未运行真实登录或部署验收。随后已只读检查本地Gateway `f6160db4`，确认HMAC login-sync、opaque token Cookie及WebSocket Cookie透传；这不是运行部署验收。
