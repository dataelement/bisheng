# F111 work120 整合与109 DSH交付记录

更新：2026-10-24。用户已授权合入最新`feat/bisheng-work-120-main`、推送、Drone构建、仅109 DSH13001部署及启动客户端联调。本文无密码、Token、HMAC或License值。完整特性验收仍与本次部署分开。

## 源码与CI

| 仓库 | 最终已推送ref | Drone | 实际结果 |
|---|---|---|---|
| BiSheng | `feat/bisheng-work-120-main` → `ecf43f79c8aa31bc645636e94b78fb1c9a74bcf9` | 5623 | SUCCESS，backend/frontend两镜像完成 |
| Gateway | 同名分支 → `faa6463b14cc908e6e507241a9d280efb040e80e`；唯一tag `v1.8.0-dsh-f111-20261024-faa6463b` | 403 | SUCCESS，amd64/arm64镜像完成 |
| Desktop | 当前隔离feature分支源`6c84d46`加T192最终补丁 | 本机 | 实际构建、启动、PKCE连接完成；模型/工具尚未验收 |

BiSheng是最新target `858f76605ca81f0cef36f42841414b797a432fac` 与F111源`3420114d0f2481d20b8854af1b84f7ca7c944c4b`的正常历史合并，保留源provider兼容修复。Gateway旧源108eb5c8存在已确证跨part漏检，不可部署；最终faa6463b含修复。两仓remote head/tag解引用均已读回。Gateway403实际stage只有clone/package/image/notify四步，115自动部署步骤由现有DSH标签条件过滤，不能把不存在的步骤描述为返回了SKIPPED状态。

## 实际镜像

镜像由CI `192.168.106.8:6082`产出，经既有`cr.dataelem.com`入口拉取，digest与CI日志逐一匹配。未修改109共享Docker daemon或insecure registries。

| 服务 | 固定镜像 |
|---|---|
| backend / backend_worker | `cr.dataelem.com/dataelement/bisheng-backend@sha256:51536d8d7b22cb195f5dca946f55b7cf7604b27f5081398f4d7da8724239f7a4` |
| frontend | `cr.dataelem.com/dataelement/bisheng-frontend@sha256:b323977b0249f1e75d3a4c09e5a5bbd925931022e694a0d3b06991c6022cdb50` |
| gateway，109 x86_64 | `cr.dataelem.com/dataelement/gateway@sha256:84a7ee17ddf44b35a43f40b30aa7c86094f116333f0c5723771dbceb979a80f7` |

实际四容器ImageID已读回对应上述digest。后续T197/T198兼容修复需要新一轮CI后单独更新，不将当前镜像冒称包含尚未发布的源码。

## 109范围、备份与执行

- 项目`dsh-bisheng`，文件`/opt/server/dsh/bisheng/docker-compose.yml`，只更新服务`backend`、`backend_worker`、`frontend`。公开13001，backend仅127.0.0.1:17860。
- 项目`dsh-gateway`，文件`/opt/server/dsh/bisheng-gateway/docker-compose.yml`，只更新`gateway`，仅127.0.0.1:18098。私网`dsh-integration`。
- 专用库`dsh_test_work110_main_20261020`、`bisheng_gateway`；现场MySQL8.0.43。没有操作109其他数据库、Compose项目或115部署。
- 备份在`/opt/server/dsh/backups/f111-20261024-predeploy`，并在真正更新前刷新到`f111-20261024-work120-before-up`，目录700/文件600。包含Compose、B/G配置、entrypoint、nginx、实际两个旧env_file、单事务两库dump、镜像身份与SHA256SUMS；备份不下载入Git。
- additive Gateway DDL实际建`gt_dsh_sensitive_policy`与`gt_dsh_safety_outbox`，创建前均不存在，创建后均0行。Backend实际Alembic从work110升级至`f111_dsh_content_safety`，保留f062积分历史。
- 配置仅追加两条精确POST模型路由，保留旧WebSocket和通配路由；精确路由不带CacheRequestBody。既有response-timeout为3600秒，与nginx预算一致。启用content-safety部署能力，namespace=`dsh109-work120`、source=`dsh109-gateway`。
- 共享HMAC以私有env_file注入Backend两服务。实际ConfigService没有自动SSOSyncConf env覆盖，故配置必须用其已存在`!env`构造器显式引用变量；用实际load_settings_from_yaml内部比较确认一致，不输出值。绑定文件替换后仅重建backend/worker，实际readback `hmac_configured=true`，签名头`X-Signature`。
- 只以`docker compose -p <exact project> -f <exact file> up -d --no-deps <exact services>`更新，未操作其他中间件或共享daemon。
- 四目标更新后Backend健康200、13001页面200。与部署前快照逐字节比较：所有其他既有容器的ID、Image和StartedAt不变；额外只有本轮临时测试Provider。

实际13001 nginx模型入口`/api/v1/dsh`经过Gateway；旧`/api/dsh`登录兼容入口直连Backend，不将登录规则误报为模型旁路。真实普通用户网络封闭验收仍未执行。

## 真实联调进度与阻塞

已用用户提供平台账号真实RSA登录并GET身份读回；会话只保存本机0600临时文件，未保存密码到仓库。通过管理API创建本轮普通用户9（非global，leaf1），未修改既有账号/角色/默认模型。现有原生审计模式CONTENT/version1，未改动。知识/评估/助手/工作台默认配置已只读快照，后续核对不被测试设施改变。

最终T192之后实际客户端再次build成功，并以独立appData/userData/session/log目录启动，Harness ready。真实Electron DOM打开企业账号，填写用户指定109 origin并确认可信内网HTTP；实际客户端生成PKCE，使用本轮普通用户真实平台会话批准，并成功抵达实际随机loopback回调。公开客户端state确认`connected=true`、`phase=connected`、`modelCount=0`。授权批准用真实HTTP API完成，此证据不冒充浏览器授权页按钮/iframe的手工UI验收。

无费用Provider最终源码SHA256 `c6bdbeaf452e84fc6c736445e705054589b4a97661266558724150a01f32c26f`，仅本轮容器`f111-provider-20261024-f111a`接入DSH私网，宿主控制端口127.0.0.1:18181经SSH。使用独立随机测试key、只读挂载、256MiB/1CPU和无外部模型连接。初始global physical model POST计数0。模型offline→私有visibility→online须待T197/T198兼容修复，禁止先上线制造公开窗口。

Gateway实际`GET /api/license/status`为`expired=true`；两个敏感词管理接口HTTP200但业务码11001。已向用户请求该测试环境有效License，不绕过许可、不将租户默认关闭下的模型通过称为敏感词通过。完整四协议/命中/工具零执行/审计与用量现场结果均仍待执行。Linux DM8按用户决定保留待验，跨租户/多副本/容量及回退演练不以单实例组件测试代替。
