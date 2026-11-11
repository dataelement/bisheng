# 昆联专属工作流创建：首批服务器更新记录

日期：2026-11-11。状态：已完成首批代码部署及冒烟核验，完整自动开通特性仍未完成。

用户在本地首批验证后要求“更新到服务器上，并提交暂存区”。本记录对应这次后续授权，不回写历史 Mock 测试为真实多租户验收。

## 部署与提交

| 项目 | 实际结果 |
| --- | --- |
| 服务器 | 192.168.106.104，工作区 `/dataelem/bisheng-kunlian` |
| 公网管理入口 | [工作流管理](http://110.16.193.170:50055/build/workflows) |
| 内网管理入口 | http://192.168.106.104:3001/build/workflows；3001 端口保持不变 |
| 发布标识 | `20261111-f130-2000`，切换完成时间 2026-11-11 19:58:03 +08:00 |
| 毕昇提交 | `34198e6105`，61 个原暂存文件，分支 `feat/v3.0.0/118-kunlian-integration` |
| 网关提交 | `bab8dd72`，3 个原暂存文件，分支 `feat/kunlian-integration` |
| 提交边界 | 两次提交树均与提交前记录的 index tree 完全一致；没有 git add 或 Git push。新增本次部署记录留在工作区，未追加进原提交 |
| 运行更新 | 同步 17 个运行源码文件（含已部署目录兼容修复的相同内容），构建 Platform 静态产物及新网关 JAR；Client 产物直接复用原版本 |
| 更新方式 | 沿用后端源码、前端静态目录与网关 JAR 的目录映射；不重新构建或拉取应用镜像 |
| 运行服务 | 重启 API、Worker／Beat 和网关的原容器；Nginx 仅校验及重载，存储服务未重建 |

此次部署包含 `create_workflow` 专属创建门禁、角色菜单、管理页新建／复制衔接、三表模型及组合配置基础。保留原人工角色与 `create_app`，不自动配置新用户角色。实际租户、模板和成员自动开通仍待后续实现；`auto_onboarding_enabled=false`，登录范围保持原 fixed 模式。组合模式继续由阶段门禁阻断。

## 备份与落点

- 备份目录：`/dataelem/bisheng-kunlian/source/backups/20261111-f130-2000`，0700。保存原源码、配置／凭据私有副本、原容器快照、原静态和 JAR 指针、数据库导出及核验记录；不得对外提供含凭据的备份。
- MySQL 全库一致性导出：6,458,328 字节，SHA256 `8bb0d6db103a4cb6d751fa1c57c69bdc4c1ca019f9ef815d0775541aec3187de`。导出通过，不代表恢复演练通过。
- 源码：`source/current/backend`、`source/current/frontend`，当前实际源目录仍为 `source/releases/20261111-management`；只更新清单中的运行文件，原文件哈希满足基线或与目标相同才覆盖。
- 静态目录：`source/static/current` → `releases/20261111-f130-2000`；新 Platform 与原 Client 一并放入新目录，813 个文件逐项哈希通过。
- 网关目录：`source/gateway/current` → `releases/20261111-f130-2000`。JAR SHA256 `8400c1b2bb7f19d91bda6f1e0f7b73a574d369fd598abce5854334acb0c038b5`，本地、宿主及运行容器一致。
- 构建日志与部署工具：`source/ops/20261111-f130-2000`；Platform 构建产物还保存在 `source/current/frontend/.static-builds/20261111-f130-2000`。

## 实际验证

| 检查 | 结果与边界 |
| --- | --- |
| 构建 | 网关使用现有 JDK 17 执行 `mvn -o -q -DskipTests package`，退出 0；复用上一批同生产代码的测试证据。Platform 使用既有容器内 Node 22／pnpm／锁定依赖构建，52.41 秒，退出 0；无依赖安装 |
| 切换前任务 | Celery inspect 返回当前 Worker 活跃任务数 0，随后执行受控停止与启动 |
| 服务 | API healthy、Worker 与网关运行，restart count 均为 0；原容器 ID、镜像、环境、挂载及网络名称保持一致，Nginx 容器启动时间未改变 |
| 配置／网络 | 16 个运行配置文件哈希保持一致。API 与 Worker 动态 IP 在重启后互换，网络与服务名不变；网关仍为 172.19.0.12，与后端既有信任配置一致，未扩大信任范围 |
| 数据库 | 仅新增 tenant_external_provision、role_external_basic_role、user_external_basic_access，均为 0 行且有 tenant_id 索引；无表删除。Alembic 仍为 f114_app_authorization。没有回填、账号迁移或人工授权变更 |
| 页面与 API | 内外网的工作流管理页、既有编辑深层路由、Client、两端 env API、登录方式及新角色文案均为 HTTP 200 |
| 页面响应时间 | 本机访问服务器：内网管理页 0.0482 秒，公网管理页 0.0495 秒；这是单次 HTML 响应耗时，不是浏览器完整首屏耗时或容量测试 |
| SSO 入口 | 已登记公网入口返回 303，跳往 ai-idp.comlansh.com:30001/oidc/authorize；未输出 state／nonce／授权参数。内网 Origin 未登记，返回 403，保持原严格入口校验 |
| 未认证创建 | 内外网直接 POST Workflow 创建均返回 401，没有创建工作流 |
| 浏览器 | Chrome 既有 admin 会话打开管理页，列表正常；新建只打开 Workflow 表单，随后取消，无对象创建或保存；未观察到控制台 error |
| 目录同步 | 更新后 requested_version=completed_version=26，policy_revision=2、enabled=1；说明已有同步仍在继续，不代表其他未映射租户自动开通 |

精简结构化证据见 [evidence-deployment-20261111.json](./evidence-deployment-20261111.json)。

检查过程已纠正：宿主系统缺 Python 且系统库不满足现有 Node 二进制，改用已有容器运行工具及构建；Docker 挂载数组顺序不作为配置变化，按目标路径比较；后端／Worker 动态 IP 如实记录，网关受信 IP 单独保持；一次性数据库探针增加显式连接关闭后无退出异常。初次 HTTP 检查误将内网授权也期望为 303，核对原 Origin 合同后改为验证拒绝，没有放松网关规则。

## 回退与未验证项

已留存并通过 `sh -n` 检查的回退入口：

```sh
sh /dataelem/bisheng-kunlian/source/backups/20261111-f130-2000/rollback.sh
```

回退先停 API、Worker 与网关，核对文件未被其他操作修改后恢复原源码和静态／JAR 指针，再启动原容器并重载 Nginx。保留数据库及三张新表，不删除用户、授权、Workflow，也不执行全库恢复。没有实际执行回退／恢复演练。

T013–T042 保持待实施或待执行；双租户自动开通、完整多租户 SSO、真实权限矩阵、MySQL 并发／事务补偿、DM8 和完整浏览器 E2E 仍未验收。本次未重新输入昆联账号走完整登录／退出，不将授权跳转探针写成完整 SSO 复验成功。
