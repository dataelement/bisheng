# 安装标识与 License 副本协调移除：本地验证记录

日期：2026-09-11。本轮完成源代码、文档与本地回归；未部署 109、未修改环境数据库、未创建 tag。真实客户端及两个独立部署环境验收仍待用户部署后进行。

## 实现范围

- Gateway：schema 2 License，不匹配机器指纹；删除 installation_id、replica-id、License 激活命令、共享门禁和心跳 ACK。各副本按当前本地 License 判断权限与席位上限，同环境仍使用 SQL 事务保护的共享席位总数。删除安装字段并调整 MySQL/DM 建表脚本和索引，保留租户/用户归属、会话轮换及操作幂等。
- 毕昇：同步内部 HMAC、HKDF、JWT、DTO、票据/Nonce key 和恢复证据目录；已有按用户/模型保存的额度、用量表不重建，无新增 Alembic 或手写业务 SQL。
- 发行工具：保留指纹输入及签名内容完整性校验，删除安装 ID 输入和字段，签发 schema 2；旧 SSO/trial/pro 兼容路径保持。测试使用临时生成的密钥。
- 开关：关闭时禁止新授权、Token、模型验权和本人详情，原有会话仍可退出。
- 客户端：7 个公开接口及 contract_version=0.5.0 不变；内部格式需两端配套切换，旧测试凭证清退后重新登录一次。详见 [兼容说明](./client-installation-unbinding-compatibility.md)。

## 执行结果

| 检查 | 结果和范围 |
|---|---|
| Gateway `Dsh*Test` | 52 passed，0 skipped；独立真实 MySQL 8 / Redis 7，包含双仓储实例 11 用户竞争 10 席、同 License 独立验证、10→2→12 本地上限变化、关闭后的退出、跨租户权限和 HMAC 向量 |
| Gateway 旧 License | `LicenseStatusHolderTest,LicenseExpiredGlobalFilterTest` 共 13 passed；DSH suite 另含旧 License Loader 兼容测试 |
| Gateway 打包 | Maven `-DskipTests package` 成功；不代表已构建/推送部署镜像 |
| 毕昇 `test/dsh` | 全量运行 420 passed、14 skipped，1 项迁移测试因复用测试库已有 user 表触发隔离保护而拒绝执行；换全新空测试库单独运行迁移与共享签名测试后 7 passed。该迁移用例本身未修改 |
| Python 跨进程恢复 | 修正测试子进程误用本地真实 Redis 配置的问题，显式使用已验证隔离测试 URL；回放/恢复测试通过，业务 runtime 不因测试修正改变 |
| License 生成器 | 6 passed；新旧格式、签名保护、finger 内容绑定、同 License 独立验证和 SSO 回归 |
| Python 静态检查 | 本次改动 Python 文件 Ruff 检查通过 |

跨语言向量位于 `contracts/shared-trust-v2.json`，两方向签名与三种 HKDF 派生结果在 Java/Python 对照。新 License 正反向量位于 `contracts/license-entitlement-v2.json`；旧 v1 文件仅为历史资料。

本地测试服务仅使用本轮创建的 `codex-dsh-unbinding-*` 容器、回环端口和测试凭据，没有连接 109。DM 实机按用户要求暂缓；已检查两种 DDL 和 Gateway SQL 兼容路径。14 个跳过用例保留为环境覆盖缺口，不算通过。两个独立 validator 验证同一 License 证明没有环境匹配条件，不代替两个实际部署环境验收。

## 部署交接

按 [rollout.md](./rollout.md) 和 [解绑修订](./installation-unbinding-revision.md) 配套切换内部协议/表结构、保留席位/模型额度/历史用量、清退旧测试凭证。移除旧 installation-id、installation_id、replica-id 配置及激活脚本调用，使用新 schema 2 License。以后普通 License 滚动更新不需要全副本 ACK。额度账本恢复审批继续保留。

交付分支：毕昇 `feat/3.0.0-beta2-pre`、Gateway `feat/dsh-access`、发行工具 `codex/dsh-license-unbinding`（独立开发分支，远端 main 未更新）。本轮不打正式或测试 tag，不部署。
