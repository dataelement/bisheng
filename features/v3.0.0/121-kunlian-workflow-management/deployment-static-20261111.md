# 工作流前端静态目录映射部署记录

2026-11-11，经用户授权，将测试服务器前端从 Vite 开发模式切换为生产构建产物目录映射，由现有 Nginx 提供静态文件。浏览器继续使用 3001 端口，未新增主机端口。API、Worker、网关及业务数据库未在本次切换中变更或重启。

管理入口：[工作流管理](http://192.168.106.104:3001/build/workflows)。客户端入口：[Client](http://192.168.106.104:3001/workspace/c/new)。

## 当前运行方式

- Platform 和 Client 均使用服务器现有源码、Node 22.16.0、pnpm 9.15.9 和已安装依赖，执行生产模式 Vite 构建。业务基线为 `5be98459b3`，包含此前已同步的卡片布局及三语文案改动。本次没有修改业务源码、依赖声明或锁文件。
- Nginx 镜像保持 `sha256:5b393c945bf2d181385d1319979b64d80baae52f5b59338dfc6e15065aae35db`，新增只读产物目录挂载，保留原 API、SSO、MinIO 与 WebSocket 转发规则。
- HTML 返回 `no-store, no-cache, must-revalidate`；Platform 带哈希脚本和样式缓存一年，Client assets 缓存一小时。JS、CSS 等启用 gzip，缺失 bundle 返回 404。
- 两个 Vite 开发容器已停止，并置于 `frontend-dev` profile；正常 Compose 启动不再依赖它们。后续更新前端需要重新构建并同步产物，不需要重新构建 Docker 镜像。

| 用途 | 服务器位置 |
| --- | --- |
| 前端源码 | `/dataelem/bisheng-kunlian/source/current/frontend` |
| 本次构建及原始日志 | `/dataelem/bisheng-kunlian/source/current/frontend/.static-builds/20261111-static-1100` |
| 本次静态发布目录 | `/dataelem/bisheng-kunlian/source/static/releases/20261111-static-1100` |
| 当前产物指针 | `/dataelem/bisheng-kunlian/source/static/current` → `releases/20261111-static-1100` |
| Nginx 产物只读挂载 | `/dataelem/bisheng-kunlian/source/static` → `/usr/share/nginx/html/deployed` |
| Nginx 配置 | `/dataelem/bisheng-kunlian/source/runtime/nginx-static` |
| 静态模式补充配置 | `/dataelem/bisheng-kunlian/docker/docker-compose.static.yml` |
| 当前 Compose 操作入口 | `/dataelem/bisheng-kunlian/source/compose-source.sh`，内容与 `compose-static.sh` 相同 |
| 开发模式 Compose 入口 | `/dataelem/bisheng-kunlian/source/compose-dev.sh` |
| 本次切换备份和核验记录 | `/dataelem/bisheng-kunlian/source/backups/20261111-static-1100` |
| 恢复开发模式脚本 | `/dataelem/bisheng-kunlian/source/restore-frontend-dev.sh` |

## 加载速度与冒烟验证

同一 Chrome 浏览器、同一 admin 会话，在独立标签访问工作流管理页。时间取自浏览器 Performance API，FCP 表示首次内容绘制。切换前为开发模式的一次观察；切换后关闭浏览器缓存测量两次，再恢复缓存刷新。开发模式资源记录达到浏览器默认的 250 条上限，不能将 250 当作实际总数，也不能直接比较两种模式的总传输量。

| 指标 | Vite 开发模式 | 静态模式，无缓存 | 静态模式，正常缓存刷新 |
| --- | --- | --- | --- |
| FCP | 16.300 秒 | 1.744 秒、1.168 秒 | 0.488 秒 |
| 资源记录数 | 至少 250 条 | 两次均为 53 条 | 54 条 |
| DOMContentLoaded | 2.859 秒 | 1.490 秒、0.945 秒 | 0.159 秒 |

这些样本表明前端启动耗时明显下降，具体耗时仍受网络、缓存和浏览器影响；FCP 不等于列表所有业务数据加载完毕。

实际完成的检查：

- Platform 构建 47.70 秒、Client 构建 1 分 27 秒，最终退出码均为 0；813 个发布产物文件 SHA256 逐一复核通过。构建保留既有大包、eval 等警告。
- Compose 配置和隔离容器内的 Nginx `-t` 通过，切换后 Nginx `-t` 再次通过。
- 管理页、新建表单打开及取消、现有 Test 工作流画布打开并不保存返回通过；未创建、保存、发布或运行工作流。
- Client `/workspace/c/new` 页面加载通过，未进行模型对话或工作流运行验证。
- 两个 SPA 的深层路由和入口引用资源均返回 200，HTML 缓存、脚本 gzip 及资源缓存规则符合配置，两个缺失脚本探针均返回 404。
- `/api/v1/env`、`/workspace/api/v1/env` 返回 200；管理页观察到的 9 项初始化接口均返回 200。API、Worker、网关的容器 ID 与启动时间在切换前后完全一致。
- 两端未观察到新增浏览器控制台错误。截图保存在本机 `/tmp/bisheng-static-management-20261111.png`。

上述为管理员部署冒烟验证。真实昆联 SSO、跨租户权限矩阵、创建并发和双方业务联调仍待执行；本次未执行数据库建表或迁移，也未执行回退演练。

## 后续更新前端

先将源码同步到服务器的对应目录，保留现有依赖与运行配置。以下命令均在服务器执行，采用新的唯一发布标识；构建未成功时，不切换当前产物指针。构建容器复用已有镜像和依赖，执行结束即退出。

```bash
TASK_SOURCE=/dataelem/bisheng-kunlian/source
TASK_RELEASE=$(date +%Y%m%d-%H%M%S)
TASK_BUILD_DIR=/workspace/.static-builds/$TASK_RELEASE
TASK_HOST_BUILD=$TASK_SOURCE/current/frontend/.static-builds/$TASK_RELEASE
mkdir -p "$TASK_HOST_BUILD"

"$TASK_SOURCE/compose-source.sh" run --rm --no-deps -T \
  -e NODE_ENV=production -e NODE_OPTIONS=--max-old-space-size=4096 \
  -e TASK_BUILD_DIR="$TASK_BUILD_DIR" --entrypoint sh platform_dev -ec \
  'node /opt/pnpm/bin/pnpm.cjs --filter @bisheng/locales build && node /opt/pnpm/bin/pnpm.cjs exec vite build --outDir "$TASK_BUILD_DIR/platform"'

"$TASK_SOURCE/compose-source.sh" run --rm --no-deps -T \
  -e NODE_ENV=production -e NODE_OPTIONS=--max-old-space-size=4096 \
  -e TASK_BUILD_DIR="$TASK_BUILD_DIR" --entrypoint sh client_dev -ec \
  'node /opt/pnpm/bin/pnpm.cjs exec vite build --outDir "$TASK_BUILD_DIR/client"'
```

两项命令均成功后，先核对两份 `index.html` 和构建日志，再发布到新目录。以下步骤同样要求任一步失败即停止，例如在 `set -eu` 的脚本中执行。

```bash
test -s "$TASK_HOST_BUILD/platform/index.html"
test -s "$TASK_HOST_BUILD/client/index.html"
mkdir "$TASK_SOURCE/static/releases/$TASK_RELEASE"
cp -a "$TASK_HOST_BUILD/platform" "$TASK_HOST_BUILD/client" \
  "$TASK_SOURCE/static/releases/$TASK_RELEASE/"

# 先记录旧指针；旧目录继续保留，供回退使用。
readlink "$TASK_SOURCE/static/current"
ln -s "releases/$TASK_RELEASE" "$TASK_SOURCE/static/current.next"
mv -Tf "$TASK_SOURCE/static/current.next" "$TASK_SOURCE/static/current"
```

Nginx 挂载的是父目录，原子切换指针后无需重建镜像或重启业务容器。刷新浏览器并检查管理页、Client、入口资源和 API。已打开的旧开发版页面需要刷新后使用静态版本。上述后续更新命令未在本次再次执行；当前发布的实际构建与切换证据见验证记录。

## 回退

恢复本次切换前的 Vite 开发模式：

```bash
/dataelem/bisheng-kunlian/source/restore-frontend-dev.sh
```

脚本先启动两个开发服务并等待健康，再以保存的开发模式配置重建前端容器，将 `compose-source.sh` 恢复为开发模式入口。只影响前端，保留静态产物。脚本已通过 `sh -n`；开发模式 Compose 配置在切换前已实际使用，但本次没有执行回退演练。

以后仅需回退某次静态产物时，将 `static/current` 原子切回仍保留的旧静态发布目录即可。首次静态部署之前没有旧静态发布目录，须使用上述开发模式回退。
