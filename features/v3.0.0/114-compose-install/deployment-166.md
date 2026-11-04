# 166 全新部署测试

日期：2026-10-29；工作分支 `codex/compose-install`，源码基线
`feat/3.0.0@3eb8f153be`，叠加本工作区部署文件。该轮验收时尚未提交或推送代码。

## 环境与隔离

- 主机：192.168.106.166，AMD64，Docker 26.1.4、Compose 2.27.1。
- 全新目录：`/root/bisheng-compose-install-test-20261029`。没有使用原
  `/root/bisheng` 的 MySQL、Redis、MinIO、Milvus 或 ES 数据。
- 首次启动前明确检查 `docker/mysql/data` 和 `docker/data` 不存在；15 个部署
  文件与 worktree 逐文件 SHA 一致，清单见 `evidence/deploy-config-sha256.json`。
- 主机原先没有运行中的业务容器，只有已停止的 bisheng-office。前后对比完整
  container ID、状态、FinishedAt，均保持一致。
- 新网络实际名 `bisheng-network`、`bisheng-sandbox`，由 Compose 创建。原
  `bisheng_default` 没有删除。没有修改 Docker daemon 或主机 sysctl。

## 镜像获取与版本边界

先按模板执行普通安装，Docker 拉取曾出现 TLS handshake timeout；降低并发后
仍出现异常慢速/反复续传。同一 CR 镜像层经普通 HTTPS 读取 8 MiB 约 0.17 秒，
故使用仅用于验收的预载工具取同一镜像，验证 manifest/config/compressed layer
SHA 和 uncompressed diffID，再 docker load；没有替换版本、重新构建或推送。
已有内容完全相同的缓存只增加 CR 别名。镜像身份见
`evidence/image-preload-results.json`。预载工具不属于客户安装依赖。

之后原安装入口（COMPOSE_PARALLEL_LIMIT=2，config → pull → up -d）返回 0。
因此已验证空业务数据首次部署，但未证明该主机无缓存 Docker 下载路径全程正常。

`feat_3.0.0` 为可变沙箱 tag：初次 manifest 的 config ID 为 `1fbef5f94f2f...`，
实际预载/验收时为 `b3718657209c...`，最终 RepoDigest 为
`sha256:b63538c05a1d1e4e80f2dbbf4f7472f56693dfba697ec7ec03667c8c1d7b1fc1`。
所有运行断言针对最终记录的镜像，不将第一次查询结果冒充相同内容。
后端/前端仍是模板固定的 v3.0.0-beta6；下载分支源码不会自动构建镜像。

## 通过的实际检查

| 检查 | 结果 |
| --- | --- |
| Compose 服务 | 13 个：12 个常驻容器运行，OpenFGA migrate 退出码 0；有健康检查的常驻服务均 healthy |
| 两套 SPA | `/`、`/workspace/` HTTP 200；浏览器登录页正常显示 v3.0.0-beta6 |
| 后端与 Nginx | `/health` 返回 OK；经 frontend `/api/v1/env` HTTP 200、业务状态 200 |
| MySQL | 首次初始化完成，bisheng 库 143 张表 |
| Redis / OpenFGA | PONG；OpenFGA 一个 store |
| MinIO / Milvus | 实际 health 端点均 200 |
| Elasticsearch | 单节点 cluster health 为 yellow；没有将其表述为 green 或 HA 验收 |
| 沙箱副本 1 / 2 | 各自获取 lease、执行 6×7 返回 42，UID 为 10000，最后释放 lease |
| 首次注册 / 登录 | 正常验证码接口生成挑战、视觉读取、RSA 密码流程；三次业务请求均 200，身份 user_id=1、role=admin；未关闭验证码 |
| Worker | Celery worker、Beat、LinSight worker 进程存在；Celery inspect ping 返回 pong，1 node online |
| Gateway | 未提供 license 文件；实际执行 --gateway --prepare-only 显示跳过，后续未创建 Gateway 或其 DB init 容器 |
| 原环境 | 已停止的 Office 容器 ID、状态与停止时间一致 |

原始结构化结果见 `evidence/runtime-checks.json`。验收账号为
`deploy_test_admin`；密码仅在测试机
`/root/bisheng-compose-install-test-20261029/test-admin.json`，权限 0600，未复制到
本地或写入仓库。实例保留，访问地址为 `http://192.168.106.166:3001`。

## 保留问题与未覆盖范围

首次双 API 进程初始化期间，一进程曾记录 initdb_config 未就绪，导致其内置技能
回填/种子步骤跳过；另一初始化进程随后完成系统配置和 3 个内置技能种子，最终
注册登录和沙箱执行通过。此启动并发日志没有通过业务代码变更掩盖，也不能据本次
结果断言所有启动竞态均已修复。

基础部署阶段没有 license 文件，随后已追加 Gateway 实测：用户提供的 license
校验为有效 pro 授权，转发/专用数据库/HMAC 均通过，详见 [Gateway 实测](gateway-166.md)。
第三方 SSO 与完整 Gateway WebSocket/SSE 业务仍未验收。
VibeApp 默认 CR 镜像尚未发布/同步，未启用 app-runtime，详见镜像核对表；没有
回退到旧测试版。没有测试 ARM 整套部署，也未配置外部模型/文档解析服务来验收
全部业务流程。
