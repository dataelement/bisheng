# F111 work120 整合与109 DSH交付记录

更新：2026-10-24。用户已授权合入最新`feat/bisheng-work-120-main`、推送、Drone构建、仅109 DSH13001部署及启动客户端联调。本文无密码、Token、HMAC或License值。完整特性验收仍与本次部署分开。

## 源码与CI

| 仓库 | 运行镜像对应源码（后续纯文档提交不改业务） | Drone | 实际结果 |
|---|---|---|---|
| BiSheng | `feat/bisheng-work-120-main` → `d5b026557b76bb57af223520c11aeecd4e83473e` | 5625 | SUCCESS，backend/frontend两镜像完成 |
| Gateway | 同名分支 → `64f602bed9fc8593cb957fb1326c229f911aae1c`；唯一tag `v1.8.0-dsh-f111-20261024-admin-denial-64f602be` | 404 | SUCCESS，amd64/arm64镜像完成 |
| Desktop | 隔离feature分支`3e8486c4da82b163d568ffde385a0304f040c698` | 本机 | build/typecheck/2820测试通过；真实两协议回复与工具正反例通过 |

BiSheng是最新target `858f76605ca81f0cef36f42841414b797a432fac` 与F111源`3420114d0f2481d20b8854af1b84f7ca7c944c4b`的正常历史合并，保留源provider兼容修复。Gateway旧源108eb5c8存在已确证跨part漏检，不可部署；faa6463b含跨part修复，64f602be另含精确旧管理拒绝映射。两仓remote head/tag解引用均已读回。Gateway404实际stage只有clone/package/image/notify四步，115自动部署步骤由现有DSH标签条件过滤，不能把不存在的步骤描述为返回了SKIPPED状态。

## 实际镜像

镜像由CI `192.168.106.8:6082`产出，经既有`cr.dataelem.com`入口拉取，digest与CI日志逐一匹配。未修改109共享Docker daemon或insecure registries。

| 服务 | 固定镜像 |
|---|---|
| backend / backend_worker | `cr.dataelem.com/dataelement/bisheng-backend@sha256:151d35b0436825c23dd9c5940300d801e8294bb1c0a75c5798250216991ef0cd` |
| frontend | `cr.dataelem.com/dataelement/bisheng-frontend@sha256:b323977b0249f1e75d3a4c09e5a5bbd925931022e694a0d3b06991c6022cdb50` |
| gateway，109 x86_64 | `cr.dataelem.com/dataelement/gateway@sha256:63d7d9eddd7b0b5c5633b8ab598f633c5ad6120d017de07221dc5fb93f75d908` |

实际四容器ImageID已读回对应上述digest。T197/T198由B5624收口，B5625只追加测试/helper与文档，bisheng业务树与3cc9de9298完全相同；当前已更新backend/worker到5625，T199/T200由G404收口；frontend两次digest相同。初次合并ecf43f79和前次Gfaa6463b构建历史仍保留，不覆盖标签。

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

最终T192之后实际客户端再次build成功，并以独立appData/userData/session/log目录启动，Harness ready。真实Electron DOM打开企业账号，填写用户指定109 origin并确认可信内网HTTP；实际客户端生成PKCE，使用本轮普通用户真实平台会话批准，并成功抵达实际随机loopback回调。公开客户端state确认`connected=true`、`phase=connected`、`modelCount=2`。授权批准用真实HTTP API完成，此证据不冒充浏览器授权页按钮/iframe的手工UI验收。

无费用Provider最终源码SHA256 `80782c04c0936c16aefeacbed35e7382b04d22901df8f97f8c567394289772fa`，仅本轮容器`f111-provider-20261024-f111a`接入DSH私网，宿主控制端口127.0.0.1:18181经SSH。使用独立随机测试key、只读挂载、256MiB/1CPU和无外部模型连接。旧计数已在Provider唯一重启前保存，active0；新进程计数取新基线，不跨进程相减。模型8/9已在offline期间GET/PUT CAS收窄仅user9、再读回确认后上线；旧默认与其他credit规则保持。

用户追加授权生成License后，使用现有官方gen_license/gateway_license.py、当前Gateway公钥匹配的sso兼容trial格式生成30天测试许可，有效至2026-11-23；仅私有0600保存和修改DSH Gateway配置，保留备份、不改许可检查。真实GET expired=false，平台聚合经现有合法状态上报同步为expiring/30days。

真实HTTP协议35/35（380.29s）、身份/管理7/7（29.83s）、十二条实际审计记录的四模式只读复核4/4（12.47s）通过。Desktop两协议正常回复、read成功各一次且文件nonce匹配、敏感参数各零工具调度，界面显示租户提示且无自动重试；BLOCKED原生模型实际结算80保持。工具结束恢复version97，随后七边界验收结束最终CAS恢复原租户策略disabled/version111。详细历史和范围见implementation-verification.md。

当前是单实例部分真实验收。LinuxDM8按用户决定待验，双租户、多副本、无Gateway、设施故障、容量及回退演练未完成，不以单实例组件测试或此次十二条只读核验替代。T121/T122/T123/T132完整任务仍不勾选。

最后边界实际7/7通过（另49本地断言），PlatformEnglish命中筛选/方向/DECISION与DRAIN详情实际通过。再次逐字节比较所有非四目标的既有容器ID/image/StartedAt不变，owned Provider健康ready。原始密码/Token/HMAC/License值未进入交付文档和Git。

CI5625 SUCCESS的源码d5b026557已远端读回；实际backend/worker ImageID e5d1403c2e1a95323dffded3858cd088a76a8ac965df186cba799e0cea8587ce。真实Backend重启后十二条旧审计四模式4PASS/13.14s。启动期首次业务读取失败保留，不能以13001/health的SPA兜底200冒后端就绪；直接127.0.0.1:17860/health与真实管理API确认后再验。Gateway日志实际连接拒绝包含旧172.31.62.10和新172.31.62.9，重建后端切换窗口确有旧地址/启动连接失败。随后四模式烟测两case通过但策略teardown真实503，停止并核精确自有合成词/提示/版本114后CAS恢复115；不隐藏失败或全局覆盖策略。待Backend业务ready后仅原镜像重建指定Gateway刷新连接，受保护capabilities连续三读成功后复验。

最终按依赖就绪顺序复验：四协议烟测4PASS/31deselected（40.27s），策略teardown全部成功；后端十二条持久审计读取4PASS（13.14s），并非全故障恢复验收。此前两case+teardown503和启动业务失败日志保留；不放宽断言、不改业务源码或重试模型求绿。最终许可证trial/2026-11-23/expired=false、全局默认模型与原审计设置不变，策略原字段恢复关闭；最后非DSH既有容器身份仍不变。后续仅features文档提交不改变src/backend构建上下文，运行镜像按本表CI5625来源记录。
