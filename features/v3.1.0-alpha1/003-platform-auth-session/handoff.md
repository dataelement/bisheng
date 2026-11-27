# F003 开发交接与集成验证入口

本轮：仅bisheng及bisheng-mobile。网关与桌面源码不改。用户已明确真实集成测试自行处理；本地开发检查不代替真实环境验收。测试结果在validation.md收尾记录；本文件不表示已部署。

## 配置与协调切换

后端沿用现有配置加载方式，增加：

```yaml
platform_auth:
  enabled: true
  public_origin: https://your-bisheng.example
  trusted_proxy_hosts: ["127.0.0.1", "::1"]
  access_ttl_seconds: 2592000
  idle_ttl_seconds: 7776000
  refresh_grace_seconds: 86400
  absolute_ttl_seconds: null
  minimum_client_version: "1.1.0"
  mobile_cutover_ready: false
  reject_legacy_web_tokens: false
```

`public_origin`替换为真实外部入口的scheme+host+可选port，不带路径；生产应显式填写HTTPS入口。未填写时回退既有`bs_client.platform_public_url`；再无配置，仅信任`trusted_proxy_hosts`中来源的转发头，默认loopback支持本机Vite代理。只有经过控制的实际反代IP/CIDR才能加入，不信任来自任意请求方的转发Host。Cookie Secure及WebView consume URL使用同一外部origin。

新Session保存Access/idle/grace和绝对到期快照，改配置默认只影响新Session。现有系统的多点登录配置在新登录准入时读取，刷新不成为新登录。

步骤1～2属于同一网页切换批次，不能只发后端后长期保留旧SPA。

1. 后端全部副本部署支持新协议的同一版本，按既有在线升级流程运行`alembic upgrade head`，确认model discovery创建独立新表。新装同样发现模型；本次没有既有表DDL，不增加冗余create-table revision。不改主JWT秘密。
2. 网页两个SPA协调发布；新手机版本`1.1.0+2`走`/api/v1/auth/login`直接取得平台凭证。切换准备期间两个cutover/reject标志均为false，旧无Origin的`/user/login`和历史手机Session协议继续原行为。
3. 用户完成手机发布准备及真实回归后，全部副本统一设置`mobile_cutover_ready: true`、`reject_legacy_web_tokens: true`。旧手机Session入口返回426，最低版本1.1.0；普通旧网页登录一次，旧DSH定向网页桥不受该拒绝规则影响。
4. 网关程序和部署配置无需本特性修改，仍HMAC调用登录同步、交付原三字段及opaque token Cookie；网页处理受限绑定。第三方OAuth2/OIDC继续原协议。真实网关、旧DSH包、真机、双DB及多实例由用户按[e2e-checklist.md](./e2e-checklist.md)执行。

`enabled: false`停止新平台Session签发，但保留已有平台Session的校验、刷新和撤销。它不等于回退到不认识新Token的旧镜像。回滚只能使用保留这些能力的地板版本；保留新表和退出记录，不恢复整库，不删除活跃凭证数据。

## 核心接口与前端注意事项

- `/api/v1/auth/login`：`client_id=bisheng-web`网页Cookie交付；`client_id=bisheng-mobile`携带真实`client_version`、原生JSON AT/RT交付。密码/验证码沿用原验证流程，不信任body传入人员或Home。
- `/refresh`轮换RT；`/session`提供metadata；`/csrf`允许有效Refresh自证以恢复过期Access；无Access Cookie但仍有有效Refresh的浏览器仍可恢复。临时故障503/10659保留本地凭据。
- `/logout`先清非秘密选择标记；logout/logout-all及其CSRF恢复可用`X-Platform-Session`选中原HttpOnly Cookie，仍需同源+CSRF；重复请求无副作用。`/logout-all`只撤销新平台会话。
- 网关入口凭证永久`bootstrap_only`，不能因绑定成功变成业务Token。绑定幂等受300秒窗口及未消费首代限制（含服务端已BOUND但响应全丢的恢复）；新旧顺序由数据库私有发行序判断；迟到绑定响应不能清掉另一场网关登录的固定名Cookie。
- Cookie按sid命名；物理保留期由cookie_retention_seconds按会话策略计算，默认121天，自定义TTL不会被硬编码截短；刷新响应不写全局选择标记。两SPA共用锁与认证控制器，Platform保持Zustand、Client保持Recoil；跨标签身份变更清理查询缓存，但不清无关偏好。
- `/web-session`交付60秒单次票据和实际host子sid，consume固定303。子sid只持Access，依赖原生parent；不将原生AT注入Cookie。真实业务顺延parent，刷新/心跳/启动读取不顺延。
- 旧DSH Token仍保持专用typ/aud及原TTL，平台30天不会放宽旧DSH codec。旧DSH轮换适配共享无IO状态决策；第三方OAuth的凭证、scope、刷新和撤销不改。

## 用户真实验证重点

优先验证Access30天与Session90天对应的离线恢复、跨副本刷新/退出竞争、网关新旧绑定迟到、多标签Web Locks及IDB退化、WS/SSE撤销5秒上限、延后执行原Access到期/撤销、旧DSH原生+内嵌网页、OAuth2 public/confidential、手机前后台与更换origin。可以在隔离环境配置短TTL测试边界；不要修改生产系统时钟。默认期限本身由单元验签/时钟测试证明。

保留脱敏版本、sid、时间差和请求原因；不得把真实AT/RT、密码、HMAC、票据或完整Cookie复制到交接文档或公开日志。

## 实施工作树（持久目录）

| 项目 | 分支 | 路径 |
| --- | --- | --- |
| bisheng | feat/3.1.0-alpha1 | `/Users/zhangguoqing/.codex/worktrees/platform-auth-alpha1-20261127/bisheng` |
| bisheng-mobile | fix/mobile-session-refresh | `/Users/zhangguoqing/.codex/worktrees/platform-auth-mobile-20261127/bisheng-mobile` |

两个原始项目目录保持原分支及已有改动；用户已另行授权分别提交并推送对应分支；提交号与远端状态以Git记录为准，未部署。工作树路径已从临时目录迁入持久目录，开发依赖中的@bisheng链接也已指向本次源码并重做类型检查。
