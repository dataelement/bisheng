# F003 实施与集成基线

日期：2026-11-27。源码事实和开发环境观察，不代表真实部署验收。用户已授权实现及测试，未部署。

## 分支与唯一写入范围

| 项目 | 基线 | 实施分支／工作树 | 边界 |
| --- | --- | --- | --- |
| bisheng | origin/feat/3.1.0-alpha1 `572d5ecf77f7b21cd0cb0d7ab3513e5cdf9cd64b` | feat/3.1.0-alpha1；`/Users/zhangguoqing/.codex/worktrees/platform-auth-alpha1-20261127/bisheng` | 后端认证Owner写src/backend；网页认证Owner写src/frontend；主执行者维护文档与集成验证 |
| bisheng-mobile | origin/main `6990f73fe10c41fb0e7171d822605fd1028d746f` | fix/mobile-session-refresh；`/Users/zhangguoqing/.codex/worktrees/platform-auth-mobile-20261127/bisheng-mobile` | 用户明确从main新建同名分支；手机认证Owner写lib/test及最少版本元数据 |
| bisheng-work | origin/main `a7a982cf1804549fc6347284c965ddb49e97916e` | 不修改 | 安装的BISHENG.app读取Info.plist为1.2.0；未据此声称与源码或目标部署等价 |
| bisheng-gateway | 本地feat/remove-dsh-seat `f6160db4` | 不修改 | 仅只读分析该源码快照，不代表生产版本 |

原bisheng工作区有beta1未提交修改，未在其源码上实施。本次不stash、reset、clean或全仓restore，开发验证阶段未自动提交或部署；用户随后已明确授权分别提交并推送指定分支。

## 生产者与消费者核对

| 入口／生产者 | 消费者／已核实事实 | 验证状态 |
| --- | --- | --- |
| Gateway BsClient.loginSync | POST `/api/v1/internal/sso/login-sync`，HMAC；OauthController读取data.access_token或data.token，并写access_token_cookie | 静态源码；真实回调待验收 |
| Gateway WebSocket routing | 收集并转发全部握手Cookie给user/info、dept及后端聊天接口，未发现只转发固定token的限制 | 静态源码；真实代理待验收 |
| Gateway buildTokenCookie | 固定Cookie落地，不保证透传额外Set-Cookie；缺少refresh字段时会使用access值；已有日志记录入口Cookie | 保留响应三字段；入口token必须永久bootstrap_only，不能绑定后获得普通业务用途 |
| 两个SPA启动与请求 | platform为Zustand，client为Recoil；共用api-client认证控制器，store边界保持 | 实施中，测试结果另记 |
| 手机密码／恢复／WebView | 改为平台直接登录；先恢复部署origin再刷新；短票据进入网页，保留host bridge兼容 | 实施中；计划交付1.1.0+2、minimum_client_version=1.1.0 |
| 普通JWT／旧DSH／第三方OAuth | 普通旧网页切换后重登；旧DSH用途和会话保持；OAuth2/OIDC只适配浏览器身份 | 待回归，不以单元测试替代安装包或第三方应用验收 |
| HTTP／WS／SSE／延后执行 | 不只验证签名，必须读Session；业务活动顺延，刷新不顺延 | 实施中，后端Owner负责完整链 |

## Schema及测试环境

- backend AGENTS §Migration policy规定独立新表通过model discovery和online upgrade的create_all(checkfirst=True)创建。现有表变更才必须写Alembic revision；本特性不修改旧DSH/OAuth表。须验证新装和升级metadata发现以及租户登记，不能只验证ORM声明。
- 可用Python：原仓库`.venv/bin/python` 3.11.13，pytest 9.0.3、SQLAlchemy 2.0.44、SQLModel 0.0.27、FastAPI 0.121.0、httpx 0.28.1；运行时PYTHONPATH必须指向当前工作树，不能误测原仓库源码。
- 本机Docker CLI可用，但经只读调用确认OrbStack daemon未运行；无独立MySQL、DM8、Redis服务程序。尚未启动任何用户服务。真实双数据库、多实例及Redis链路验收条件未就绪。
- node/pnpm可用；网页依赖的@bisheng工作区包需显式指向当前工作树，避免链接到原仓库旧源码。
- 实施初期Flutter/Dart不在PATH；后已通过官方GitHub取得Flutter3.47/Dart3.13，原lock强制校验通过，无依赖降级，209项最终测试通过。SDK位于/private/tmp/mobile-flutter-sdk-3.47。

## 放行约束

源码测试、构建、实际SQL+HTTP、外部环境验收分别记录。单元测试／SQLite不能冒充MySQL或DM8事务证明，静态Gateway检查不能冒充网关端到端，桌面Info.plist不能冒充旧包登录回归。全量拒绝普通旧JWT前必须完成手机发布准备；不改变主签名秘密。

## 用户更新执行边界

用户明确真实集成测试由其处理，本轮开发者完成代码及单元测试。双DB、多实例、真实网关、旧DSH安装包、iOS/Android真机由用户在其环境验收；未部署，不将这些项目记为通过。
