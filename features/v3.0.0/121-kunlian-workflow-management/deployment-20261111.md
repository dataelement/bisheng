# 工作流管理页目录映射部署记录

2026-11-11 在测试服务器 `192.168.106.104` 完成部署。部署内容为 `feat/v3.0.0/118-kunlian-integration` 当前工作区，包含工作流管理页及审查修复。工作区基线为 `c0475c8ce`，源码快照包含尚未提交的改动。

管理入口为 `http://192.168.106.104:3001/build/workflows`，客户端入口为 `http://192.168.106.104:3001/workspace/`。

## 运行方式

| 服务 | 目录映射及运行方式 |
| --- | --- |
| 后端 API、Worker | 将服务器源码中的 `backend/bisheng`、`backend/bisheng_langchain` 只读映射到原容器的 `/app/bisheng`、`/app/bisheng_langchain`，复用镜像内的 Python 依赖。配置和运行数据仍分别挂载。 |
| Platform | 映射 `frontend` 工作区，用 Vite 运行源码，内部端口 3001，Nginx 将管理端请求转发到该服务。 |
| Client | 使用同一前端工作区，用 Vite 运行源码，内部端口 4001，Nginx 将 `/workspace/` 转发到该服务。 |
| 网关 | 使用现有商业网关，经 Nginx 处理浏览器 API 与登录请求。本次重启网关以刷新后端容器地址。 |

前端为联调开发模式。Node 22.16.0 的 Linux 二进制经官方 SHA256 校验后只读挂载，pnpm 为项目指定的 9.15.9，依赖按锁文件安装。因镜像拉取受限，前端开发服务复用服务器已有的运行镜像，并覆盖启动命令。

服务器文件位置如下。

| 用途 | 路径 |
| --- | --- |
| 当前源码入口 | `/dataelem/bisheng-kunlian/source/current` |
| 本次源码实体目录 | `/dataelem/bisheng-kunlian/source/releases/20261111-management` |
| Compose 补充配置 | `/dataelem/bisheng-kunlian/docker/docker-compose.source.yml` |
| Vite、Node 与 Nginx 运行配置 | `/dataelem/bisheng-kunlian/source/runtime`，Vite 补充配置分别位于两个前端应用目录的 `vite.source.config.mts` |
| Compose 操作入口 | `/dataelem/bisheng-kunlian/source/compose-source.sh` |
| 回退入口 | `/dataelem/bisheng-kunlian/source/rollback-source.sh` |
| 切换前配置备份 | `/dataelem/bisheng-kunlian/source/backups/20261111-management` |

## 后续更新

目录映射读取服务器上的文件。本机代码需要先同步到服务器的对应源码目录，并保留服务器运行配置与 `node_modules`。

- 前端源码同步到 `source/current/frontend` 后，Vite 自动处理模块更新，浏览器会热更新或刷新。修改依赖时需按锁文件重新安装依赖并重启前端服务。
- 后端源码同步到 `source/current/backend` 后，在服务器执行以下命令使 API 和 Worker 使用同一份新代码。

```bash
/dataelem/bisheng-kunlian/source/compose-source.sh restart backend backend_worker
```

查看服务状态或重启前端可执行以下命令。

```bash
/dataelem/bisheng-kunlian/source/compose-source.sh ps
/dataelem/bisheng-kunlian/source/compose-source.sh restart platform_dev client_dev
```

后端依赖和迁移文件与部署前镜像一致。本次目录映射更新复用了现有依赖和数据库结构。后续涉及依赖或数据库结构的更新，需按对应变更重新核对。

## 实际验证

- 5821 个源码文件逐一校验 SHA256，与上传快照一致。快照清单位于本次源码实体目录的 `source-manifest.json`。
- 源码部署和回退两份 Compose 配置检查通过，Nginx 配置检查通过。API、Platform 和 Client 服务健康，Worker 运行。
- 公网入口仍使用主机端口 3001。两个 Vite 服务均只接入容器网络，后端仅在主机回环地址提供 7860。
- 使用浏览器已有的 `admin` 会话，实际打开管理页、查看现有 `Test` 工作流、打开并取消新建表单、打开画布并通过未保存确认返回管理页。保留了现有工作流内容。
- Client 实际加载至 `/workspace/c/new`。
- 切换后发现网关保留了旧后端地址 `172.19.0.9`，导致部分配置查询失败。重启网关后重新加载管理页，所观察到的 API 响应全部恢复成功。

上述为部署后的管理员冒烟验证。多租户普通账号、只读与编辑权限矩阵、实际创建并发和昆联 SSO／目录同步的完整联合验收继续待执行，T035、T036 保持 `NOT_RUN`。

## 回退

需要恢复切换前的镜像运行方式时，在服务器执行以下命令。

```bash
/dataelem/bisheng-kunlian/source/rollback-source.sh
```

脚本使用已保存的镜像 ID 和原配置重建 API、Worker、Nginx，重启网关以刷新地址，然后停止两个 Vite 服务。回退配置已通过 Compose 静态检查，回退动作尚未执行。持久数据及配置备份保留在服务器。
