# 工作台多选与 config 修复：109 部署记录

日期：2026-11-07（America/Los_Angeles）。用户明确授权部署到 109 供手动验证。

访问地址：[109 平台](http://192.168.106.109:13001/)。登录租户管理员账号后进入市场的工作台内容区，点击导入，可选择多个 TGZ。只导入通过项，有效升级走现有版本规则；失败文件独立显示原因。

## 本次发布

- 本地代码基于 main 的 62f5893912a171265769f004fe79a96cfb009fee；前次 config 安全校验与本次 TGZ 多选均包含。工作树尚未提交、合并或推送，以源码/构建哈希和镜像 ID 追溯本次发布。
- 后端基于 109 原有固定镜像制作增量镜像，仅覆盖 workbench_bundle.py、工作台 endpoints.py 和 dsh_market 错误适配三处；现场 pyproject.toml 与 uv.lock 的 SHA-256 均与本地完全一致。
- 平台通过 pnpm --filter bisheng build 构建。静态目录 671 文件、46,042,829 字节；用 109 原有前端镜像作为基底替换平台目录，保留原客户端和 nginx 配置。
- Compose 仅替换 backend、backend_worker、frontend 三项镜像引用，配置校验后通过 up -d --no-deps --pull never --wait 切换。保留原数据库、绑定配置、端口、网关和其他测试环境。

| 服务 | 新镜像 ID | 验证结果 |
| --- | --- | --- |
| backend / backend_worker | e505e3161708d25efffd13460e85a3afa302f640249784f62ef17a3a89fcecb3 | 后端 healthy，worker running，重启次数均为 0；worker 无独立 healthcheck |
| frontend | 770bdb9037a5556eb2ca2fbe9a401babef3ec13f384156313062cf9dddc7a324 | running，重启 0；nginx -t 通过、公开 HTTP 200；无独立 healthcheck |

镜像 tag 均使用 workbench-multiselect-20261107-62f589391 后缀，保存于 109 本地 Docker。

## 验证证据

- 在发布后端镜像 Python 3.11.15 中运行静态验证：原始思维导图 1.0.15 TGZ SHA-256 保真且通过，传统 name/id 包通过；配置类型、危险表达式、空白 ID、多插入、包名不一致 5 项均拒绝，并保持外层数值 26205 与内层具体校验码。
- 发布后三个后端源码的 SHA-256 与本地已测试源码完全相同。
- 后端 /health 返回 {"status":"OK"}；平台首页公开地址返回 200。
- 对外首页 SHA-256：52536e497e5e10fb514483c9dbab6d919866a3c99ddf07d1ebb6621222cd2d6d；入口 index-DXzq5ZI7.js：945d82d939a499cc32017f7ee0157d6d273fe0a66a931072f50ea8113bada1b2。均与本地构建一致。
- 对外 zh-Hans/dshMarket.json 与 api_errors.json 哈希均与本次构建一致，三语言多选键在构建时验证。
- tabbit 真实浏览器打开并刷新了 109 页面，登录页完整渲染，无 pageerror；当前无登录态。市场管理员 context 返回 HTTP 200 / 业务 401（Enterprise login required），权限边界有效。登录后的上传操作留给用户验收，未把登录页冒充业务操作验收，也未导入测试数据。
- 先前针对性前端 74 项、后端工作台 39 项和质量门禁结果见[多选规格](workbench-multiselect-spec.md)。alpha3 安装运行验收仍不在此次平台部署证据内。

## 回滚点

原后端镜像 ID：0de6201ec910c671d47e9446dbf1a35f2f95ebdbfd44939638086c552097984e；原前端：a2f99b361451efdb58d6a5b397261f8b9c423c1ef9f26d31cc4a1f98e6c9f650。均已在 109 打 rollback-workbench-20261107 标签，原 Compose 与容器 inspect 已保存在权限 700 的备份目录。

以下是需要回滚时在 109 执行的命令，本次未执行回滚：

```bash
cp /opt/server/dsh/bisheng/backups/workbench-multiselect-20261107-62f589391/docker-compose.yml /opt/server/dsh/bisheng/docker-compose.yml
chmod 600 /opt/server/dsh/bisheng/docker-compose.yml
docker compose --project-directory /opt/server/dsh/bisheng -p dsh-bisheng -f /opt/server/dsh/bisheng/docker-compose.yml up -d --no-deps --pull never --wait --wait-timeout 120 backend backend_worker frontend
```

发布上下文与不含密钥的 release-manifest.json 存放在 109 的以下目录，备份中包含敏感配置，应仅由管理员访问：

```text
/opt/server/dsh/releases/workbench-multiselect-20261107-62f589391/
/opt/server/dsh/bisheng/backups/workbench-multiselect-20261107-62f589391/
```

## 后续调整：上限由 20 放宽到 50

2026-11-07 用户确认仅放宽数量上限；已同步三语言提示和规格。单包 8 MiB、总计 64 MiB 不变。针对性回归现为 6 文件 75 项通过，新增 50 个全部导入边界，51 个继续在请求前拒绝；lint、typecheck、check-i18n、locales:check、平台 build 和 arch-guard 均通过。

109 仅重新部署 frontend，后端和 worker 未重启。当前前端镜像 ID 为 49ec00c520d2cd7e40a0b64107e9fcfbf1a77ea0e672f424b8eff4575fba230e（tag：workbench-limit50-20261107-62f589391），running、重启 0；后端仍为原 e505e316 镜像，/health 返回 OK。

对外首页 SHA-256 为 00cc0280a8b27f49510a98292776765d6d1d4450f98552e2baa9036736e15980；工作台资源 index-CkOiT1TG.js SHA-256 为 023e2645fda16d585e9b37ddd9f791d3fbbf20d9eadeb64463a9c976528b1b24，均与本地构建原始字节完全一致；已检查其编译后的数量判断为 length > 50，三语言对外提示均为 50。

此次调整的回滚快照保留于以下目录，可恢复到原 20 包限制的前端；此前首次发布回滚点也保留。

```text
/opt/server/dsh/bisheng/backups/workbench-limit50-20261107-62f589391/
/opt/server/dsh/releases/workbench-limit50-20261107-62f589391/
```

## 2026-11-08：同版本覆盖、100 MiB、管理页删除

本次更新 backend、backend_worker、frontend；同版本可覆盖内容并更新摘要，工作台单包 100 MiB、批量仍 50、移除 64 MiB 独立批次门槛，管理员可 revision CAS 删除后重新导入恢复。无 schema 迁移、无数据回填、无共享制品删除。

本地 Python 3.11.15/uv.lock 冻结依赖全市场 118 项通过；前端 8 文件 100 项通过，全部质量门禁和生产构建及七维源码审查 PASS。109 候选镜像原始配置包/覆盖/删除/恢复/租户隔离自检通过。SSH 初期拒绝，用户修复登录后重新读取当前 Compose，快照 SHA-256 328bf257fea6b9f9baa71aed7b5c834ad3ac1be2187c03d470f34f1ceee978ff，并用 cmp 检测并发变更后切换；部署脚本具备失败自动回滚。

- 后端与 worker 镜像 ID：79055ed77864232c32bbcea946b17fe80be0d07118b34177ab583b76914a9f04。
- 前端镜像 ID：a2fb9dcd9ae3ce1247915a9643e1fe5a0367dbcbd30410b554fda1e29c9d1e27。
- 三服务 running、重启 0；后端 healthy，/health OK，nginx -t 通过。
- 对外首页 SHA-256：d50d1e40353db6a85f89686fd262b31d6c09e9b3cdf2ccb5b8d10fb505048971，功能 JS 与三语言 locale 亦匹配最终构建。
- 实际 nginx 上限 1024m/读取超时3600s，无需变更；实际 100 MiB 文件+191 字节封装通过代理，未登录预览与 DELETE 均返回业务401，无正式业务写入。
- 已登录业务 UI/真实数据库与 MinIO 全旅程未手工执行，完整分层证据见 workbench-overwrite-delete-validation.md。

当前发布及回滚点：

```text
/opt/server/dsh/releases/workbench-overwrite100-delete-20261108-62f589391/
/opt/server/dsh/bisheng/backups/workbench-overwrite100-delete-20261108-62f589391/
bisheng-backend:rollback-workbench-overwrite100-delete-20261108
bisheng-frontend:rollback-workbench-overwrite100-delete-20261108
```

如需回滚，将本次 backup 的 docker-compose.yml 恢复到部署目录，使用原 dsh-bisheng 项目 up -d --no-deps --pull never --wait backend backend_worker frontend；将恢复到本轮之前的后端 e505e316、前端 49ec00c5（50 包限制）镜像。不得使用本地旧 Compose 覆盖新的环境变更，执行前先保存当时的实际配置。
