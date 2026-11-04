# 166 Gateway license 实测

日期：2026-10-29；工作分支 `codex/compose-install`，基线 `feat/3.0.0@3eb8f153be`。
在上一轮空数据部署的 166 实例上追加启用 Gateway，不是第二套空数据部署。

## 结果

用户提供的 license 已由 Gateway v1.8.0 实际校验通过：`version=pro`、
`expired=false`，`checked_at=2026-10-29T21:03:00.507744355+08:00`。
永久授权的 `severity=unknown` 为该版本既定返回值，不代表尚未校验；
判断同时检查了版本、过期标记和非空校验时间。

访问地址：http://192.168.106.166:3001 。实例保留 Gateway 开启状态。

| 检查 | 实际结果 |
| --- | --- |
| 授权接口 | 外部 Nginx `/api/license/status` HTTP/业务状态均 200；浏览器也读到相同有效 pro 状态 |
| API 转发 | `/api/v1/env`、`/workspace/api/v1/env` HTTP/业务状态均 200，`data.pro=true` |
| Gateway 自有接口 | `/api/oauth2/list`、`/api/getkey` HTTP/业务状态均 200 |
| 页面 | `/`、`/workspace/` HTTP 200；浏览器刷新登录页正常 |
| Nginx | `nginx -t` 通过；安装器生成 Gateway 转发配置并挂载生效 |
| 专用数据库 | init 容器退出 0，bisheng_gateway 库 6 张表；专用账号实际连接成功 |
| HMAC | Gateway/backend/worker 的密钥一致且非空；内部 login-sync 空对象请求，未签名业务码 19301，正确签名业务码 422（进入参数校验），没有创建或修改用户 |
| 文件/端口 | license 文件与 .env 均 0600，license 只读挂载，Gateway 没有发布宿主端口 |
| 服务 | 15 个服务：13 个常驻容器运行、两个初始化容器退出 0；有健康检查的常驻容器均 healthy，Gateway 重启计数 0 |
| 原环境 | 原 Office 容器完整 ID、状态和停止时间与此前保护快照一致 |

脱敏结构化证据：[gateway-166-checks.json](evidence/gateway-166-checks.json)。
license 原文、HMAC、数据库密码和登录凭据没有写入仓库或本文。
license 文件只保存在 166 测试目录的 `secrets/gateway-license.txt`，父目录权限 0700；
安装器仍要求用户提供可读 license 文件路径。验收辅助程序不属于客户安装依赖，
产品安装入口仍然只依赖 Shell 和 Docker Compose。

## 镜像与安装命令边界

Gateway 使用 `cr.dataelem.com/dataelement/gateway:v1.8.0`，manifest 为
`sha256:3539060dd29f23489f8f20321bb5b180a34600355da26640e29cf5e5109b4e18`，
实际镜像 ID 为
`sha256:d17be79b2e72d043f34187b196e886f912a6d9a6a09155fd30fb03c0a0bbd66a`。
166 原生 Docker pull 再次出现 TLS handshake timeout，使用既有验收辅助工具
验证同一镜像 manifest/config/layer/diffID 后预载，没有替换版本或重新构建。

现有 install.sh 已完成 license 文件读取、随机密钥生成、profile/商业版标识和
Nginx 配置生成，并通过 Compose 配置校验。随后全量 pull 阶段遇到可变沙箱 tag
再次更新及下载异常慢，主动停止，安装器按预期在 up 之前退出；不能将该次完整
安装入口记为成功。为继续 license 测试，在同一份生成配置上显式使用已校验缓存：

```shell
docker compose up -d --pull never gateway
docker compose up -d --pull never
```

这两个命令均返回 0；没有为环境网络问题改动产品安装器。
沙箱仍使用上一轮验收过的镜像 ID `b3718657209c...`。此次查询仓库临时 tag 的
config 已变为 `7954189b2286...`，manifest 为
`sha256:65629aefa1b0569b02c0a6d2070fd974ec53b6a644a3db8c75100385200a363a`；
没有把未下载的新内容当作已验收镜像。

## 未覆盖范围

没有配置真实 SSO/LDAP/企业微信提供方，所以这次只验证 HMAC 信任边界和
Gateway 基础入口，未验收第三方登录。未使用模型运行完整 WebSocket/SSE 业务，
未启用缺少默认 CR 镜像的 VibeApp app-runtime，也未测试 ARM。
普通无缓存 Docker 下载链路仍有上述环境问题。
