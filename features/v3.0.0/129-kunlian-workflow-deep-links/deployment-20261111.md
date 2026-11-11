# 编辑直达入口部署记录

**Date**: 2026-11-11
**状态**: 本批服务器更新与管理员冒烟验证通过；真实昆联 SSO 和完整特性验收待执行。

用户在 T004–T009 本地验证完成后授权更新测试服务器。本次发布已完成的 T001–T009 运行代码，不包含尚未实施的 Client 执行边界、后端当前发布快照等任务。仍以 3001 为唯一浏览器入口，使用静态文件＋目录映射＋Nginx；没有推送 Git 或创建提交。

## 1. 已部署内容

| 部分 | 更新内容 |
| --- | --- |
| 前端共享包 | 链接解析与登录尝试工具、callback 初始阶段查询及导出。 |
| Platform | 编辑链接识别、早期非法参数拒绝、实际用户查询与入口资格、SSO 目标保留及失败重试、请求错误交接。 |
| Client 静态产物 | 因共享包更新一并重新构建；不包含尚未实施的执行入口功能。 |
| 商业网关 | 新构建的可执行 JAR，通过只读目录映射启动，包含可信事务目标的失败页重试改动。保留原镜像、Java、环境变量、配置及 License 挂载和网络。 |

仅同步前端 8 个运行源码文件，服务器原文件与本地 HEAD 基线一致后才覆盖；旧文件已归档。生产镜像、依赖声明、锁文件、数据库和业务权限配置未修改；API、Worker 和存储服务未重建。切换网关后重载 Nginx，以刷新上游地址。

## 2. 服务器落点与回退

| 用途 | 位置 |
| --- | --- |
| 测试站点 | `http://192.168.106.104:3001` |
| 发布标识 | `20261111-f129-1247`；实际切换时间 12:53:57，Asia/Shanghai |
| 源码 | `/dataelem/bisheng-kunlian/source/current/frontend` |
| 前端构建与日志 | 上述目录的 `.static-builds/20261111-f129-1247/` |
| 当前静态目录 | `/dataelem/bisheng-kunlian/source/static/current` → `releases/20261111-f129-1247` |
| 原静态目录 | `releases/20261111-static-1100`，保留 |
| 当前网关目录 | `/dataelem/bisheng-kunlian/source/gateway/current` → `releases/20261111-f129-1247` |
| 网关旧程序 | `/dataelem/bisheng-kunlian/source/gateway/releases/20261111-before-f129/gateway.jar` |
| 网关目录只读映射 | `/dataelem/bisheng-kunlian/source/gateway` → `/opt/bisheng-gateway` |
| 网关运行补充配置 | `/dataelem/bisheng-kunlian/docker/docker-compose.gateway-runtime.yml` |
| Compose 操作入口 | `/dataelem/bisheng-kunlian/source/compose-source.sh` 和 `compose-static.sh`，已同步包含网关补充配置 |
| 备份与核验记录 | `/dataelem/bisheng-kunlian/source/backups/20261111-f129-1247`，目录权限 0700 |
| 运行版本回退 | `sh /dataelem/bisheng-kunlian/source/backups/20261111-f129-1247/rollback.sh` |

回退脚本先停止网关，再恢复旧网关 JAR 指针并重建网关、恢复旧静态指针、重载 Nginx。不清理数据库或会话，不覆盖源码；旧源码另保存在备份中的 `frontend-before.tar.gz`。脚本语法检查通过，**本次没有实际执行回退演练**。

网关每次更新 JAR 后仍须重启／重建网关，Java 不支持靠刷新页面加载新 JAR；目录映射可省去重新构建网关镜像。前端每次仍需构建新的静态产物，再切换指针。

## 3. 构建及完整性

- 服务器复用已有 Node 22.16.0、pnpm 9.15.9 和锁定依赖。Platform 构建 48.52 秒，Client 构建 1 分 24 秒，退出均为 0；保留既有大包及第三方 eval 警告。构建及复制到新目录后，813 个静态文件 SHA256 检查通过。
- 网关使用已有 Java 17，执行 `mvn -B -DskipTests package` 成功；复用同代码状态下 12 项 controller 测试证据，不重复运行。初次构建因一个 Spring Boot 构建插件依赖的 TLS 下载失败；从 Maven Central 下载并校验其官方 SHA1 后补入本机缓存，再次构建成功。未修改 POM 或依赖版本。
- 新网关 JAR SHA256：`a5d3da29a74b4cfa41861d84b279c632eb2aed87bf370cae734e2daa14edafac`，本地、服务器及运行容器内一致。
- 原网关 JAR SHA256：`9a91934d100afbccc24d3d5358ce3a8a5b91c30a1c36475deacb01746f43b3c9`，旧程序已保留。
- 新网关容器的镜像 ID、完整环境变量和 Docker 网络与更新前逐项比较相同；新增的只有运行目录只读映射及对应 JAR 启动路径。原配置和 License 挂载保持相同。
- Compose 配置与 Nginx `-t` 通过。网关运行正常、重启计数 0；API、Worker、Nginx 容器 ID 与启动时间在前后核对一致，仅 Nginx 进程执行配置重载。

## 4. 实际冒烟验证

使用 Chrome 中已有的 admin 会话，未创建、保存、发布或运行 Workflow。

| 项目 | 结果 |
| --- | --- |
| `/build/workflows` | `PASS`，列表和既有 Test 工作流正常显示。 |
| 指定 Workflow 编辑直达 | `PASS`，下述链接打开 Test 的 v0 画布，保留来源和昆联入口参数，没有重复授权。 |
| 编辑直达刷新 | `PASS`，仍打开原工作流；开始节点及原有节点菜单正常显示。 |
| 画布返回 | `PASS`，出现既有未保存提醒后选择“不保存”，返回 `/build/workflows`；未点击保存。 |
| `/workspace/c/new` | `PASS`，Client 页面加载；未进行对话或工作流执行。 |
| 两端页面与 API | `PASS`，管理页、编辑深层路由、Client、`/api/v1/env`、`/workspace/api/v1/env` 返回 HTTP 200。 |
| 浏览器控制台 | 本次两个验证标签未观察到 error 日志。 |

已验证的编辑链接：

```text
http://192.168.106.104:3001/flow/2c3bcfd3f5d840ec9d68e8027644aac4?from=workflow-management&entry=kunlian
```

本例仅证明当前 admin 会话可编辑该对象；不证明昆联用户已准入、跨租户权限或真实 SSO 已通过，也不证明该对象已上线。

## 5. 仍待执行

- 真实昆联 SSO：当前 `/api/oauth2/list` 返回 HTTP 200，但登录方式为空；授权入口探针返回 HTTP 503、`DEPENDENCY_UNAVAILABLE`。未修改当前认证配置或凭据，不能将本次部署记为 SSO 联调成功。
- 具备不同对象权限、不同租户的受控账号验证；真实 MySQL／DM8、OpenFGA 与队列验收。
- T010–T027 的剩余开发及完整浏览器闭环。T031 仅完成本记录中的编辑侧部署冒烟，完整验收仍 `NOT_RUN`。
- 全局 lint 仍存在上一批已记录的失效抑制清单问题；定向 lint、类型检查、63 项 Platform 回归与 12 项网关测试已通过，详见 [验证记录](./verification.md)。
