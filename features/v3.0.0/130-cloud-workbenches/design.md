# Design: 企业云端工作台

**关联**：[spec.md](./spec.md) · [tasks.md](./tasks.md)。**版本**：v3.0.0 work-130。**最后更新**：2026-11-09。

本设计补记 PR #2595 `b45d8258d3` 的已实现行为及此次集成验证，不追认不存在的历史确认。遵循 `docs/constitution.md`；领域归属继承 [release-contract.md](../release-contract.md) 的 F054/F055/F062 和权限运行时。

## 1. 目标与非目标

在既有托管应用上增加桌面自然人入口、开发发布适配和统一目录。保留原发布审批、资源动作及运行时编排边界。此仓库不实现 Desktop 工程管理与安装包，也不将 SQLite 协作扩展成多个实例同时写入。

## 2. 关键约束

桌面身份来自当前设备会话，不签发服务账号凭据。后端不持有编排权限；托管实例由 runtime-manager 管理。API、worker 与代理共享访问状态时使用 Redis/数据库，源码快照使用对象存储。SDK 里的 SQLite 属于托管业务应用的既有单写入持久卷，不是平台多节点间共享状态。

## 3. 方案对比与选定

### 决策 1：单应用票据与设备会话引用

备选为复用网页主 Cookie、发放静态服务账号 Key、或一次性应用票据。选定应用票据：Redis 只以摘要寻址，60 秒票据通过 Lua 原子校验 slug 并消费，兑换 3600 秒的 `bs-view-` 会话；会话引用保留设备身份。每次入口判定重新校验设备会话、当前账号和 use 动作。原因是无需暴露主凭据且撤销设备身份后仍可封闭访问。若跨站嵌入或设备会话协议改变，重新评估 Cookie 和生命周期合同。

### 决策 2：发布复用现有流水线并延迟校验

备选为独立桌面发布逻辑或适配 PublishPipelineService。选定适配：`DesktopPublishIdentity` 保存自然人及 `dsh_session` 引用；后台执行由 RuntimeAuthorizationService 重新解析当前身份和权限。AdmissionRepository 锁定应用行，在接收发布记录的事务中再次检查发布状态和当前版本。原因是扫描、审批、发布审计不能在两个入口分叉。若发布状态机改变，应同时回归 CLI、Web 和 Desktop 入口。

### 决策 3：冻结源码导出与统一目录

备选为返回脱敏审读文本或原始快照。选定从 VersionService 的固定版本快照安全解包、按目录/扩展过滤并扫描密钥后重新归档，返回摘要和应用/基线身份。目录复用 tenant、state 和资源动作判定，以数据库行游标继续扫描；被过滤行可导致空页但仍有 next_cursor。若源码过滤规则影响可构建性，需同时更新导出测试和桌面检出合同。

### 决策 4：单写入 SQLite 的事务记录和事件日志

备选为浏览器唯一存储、多实例共享文件或既有应用持久卷。选定 RealtimeStore 在一个 SQLite 事务中写记录 revision、按 actor 隔离的幂等结果与失效事件；读取快照和游标也在同一事务中完成。原因是符合现有托管应用单写入合同。需要多实例或逐字共同编辑时，应另行设计服务端共享存储和协同协议。

## 4. 系统现状

### 4.1 数据流

目录：`GET /api/v1/apps/workbenches` 或 `GET /api/v1/dsh/apps` → DesktopAppRepository → workbench_page → 当前租户、上线状态及 use 动作过滤；桌面 managed=true 改为编辑权限目录。

打开：桌面 launch → DesktopAppsService.require → Redis ticket → `POST /apps/{slug}/_desktop` → HMAC 内部兑换 → scoped Cookie → authorize_desktop_entry → 既有 authorize_entry → 托管应用。代理去除平台凭据和桌面 Cookie 后才转发；SSE / WebSocket 定期重新鉴权。

开发：source endpoint → edit 检查 → 固定版本快照过滤/扫描 → 归档与 SHA-256 → Desktop 配套工具安全检出。发布：deploy endpoint 在读取 multipart 前认证 → DesktopPublishService → PublishPipelineService.accept → 设备会话引用落库 → worker 重新鉴权 → 原扫描、构建、预检与审批链路。

### 4.2 字段与接口约定

| 契约 | 格式与语义 | 消费者 |
| --- | --- | --- |
| list `items / next_cursor` | 应用 id/name/slug/description/state/version_id/entry_path；Web 追加 entry_url | Web、Desktop |
| launch | app_id、slug、entry_path、launch_path、ticket、expires_in=60；ticket 不进入业务应用 | Desktop |
| `bisheng_app_session_{slug}` | HttpOnly、SameSite=Strict、Path 为应用入口；HTTPS 时 Secure；max_age=3600 | app-proxy |
| source | gzip；X-Source-SHA256、X-App-Id、X-Base-Version-Id；Cache-Control=no-store | Desktop 检出 |
| deploy | package、可选 app_id/base_version_id/release_notes/confirm_schema_change；成功返回 app_id/deployment_id/version_id | Desktop 发布 |
| runtime credential_ref | kind=dsh_session，principal 为 tenant_id/user_id/session_id 引用；不保存 Token | 异步发布鉴权 |
| SDK collaboration | write 的 expected_revision、operation_id、actor；snapshot 的 cursor/records；events 的 seq/collection/record_id/revision | 业务应用 |

### 4.3 模块职责

| 模块 | 职责 |
| --- | --- |
| dsh/api/endpoints/apps.py | 设备会话 API 和上传前认证 |
| app_runtime/domain/services/desktop_apps_service.py | 当前身份、租户与资源动作判定 |
| app_runtime/domain/repositories/desktop_app_sessions.py | Redis 票据和应用会话 |
| app_publish/domain/services/desktop_publish_service.py、source_export.py | 自然人发布适配及源码导出 |
| dsh/application/runtime_identity.py | 重新解析持久化的设备会话引用 |
| app-proxy/desktop.py、sse.py | 应用 Cookie 兑换、持续连接重新鉴权 |
| bisheng_sdk/realtime.py | 单写入应用事务协作数据 |

## 5. 已知坑

| 事实 | 不知道的后果 | 处理处 |
| --- | --- | --- |
| 仅在上传时鉴权不能覆盖排队期间的会话撤销 | 被撤销身份继续执行发布 | RuntimeAuthorizationService 的 dsh_session 分支 |
| 普通 app use 不等于源码 edit | 源码泄漏 | source endpoint 在读取归档前 require(edit) |
| 目录页过滤后可为空但仍有下一页 | 客户端错误判断“无应用” | workbench_page 保留扫描游标 |
| SDK 幂等摘要包含完整值和预期 revision | 重试生成新时间戳会被视为不同操作 | 在线指南和 RealtimeStore.write |
| SSE 即使没有业务事件也要重新鉴权 | 空闲订阅无限保留撤销前权限 | authorized_events 的独立 deadline |
| F113 已属于服务账号租户一致性 | 维护者误关联既有 feature | 本文档使用 F130；历史代码中的 F113 注释不代表领域归属 |

## 6. 对外契约与依赖

提供上述 DSH / Web 目录、源码与发布 API，公开 workbench-guide.md / workbench-guide-en.md，以及 SDK 0.1.2；保留 SDK 0.1.1 下载和校验。开发工具分发路由受既有 open_platform.enabled 进程配置控制，关闭时不注册路由并返回 404；云端运行和入口另受 app_runtime.enabled 控制，镜像更新不会自动启用原来关闭的能力。依赖 F054 应用状态、F055 发布流水线/固定版本快照、F062 设备会话、F048 业务动作授权、对象存储与 Redis。配套桌面 PR #125 必须另行部署；旧 app-proxy 不识别新票据入口，因此后端/前端升级不代表桌面入口交付完成。

## 7. 测试与可观测

test/cloud_workbench 验证隔离、票据一次性和会话撤销；test/app_publish/test_desktop_publish.py 验证源码权限、基线及真实发布记录落库；dev_toolkit 测试验证在线指南与历史 SDK；代理测试验证 Cookie 过滤和 SSE 断权；SDK 测试验证事务、CAS、幂等及 HTTP 样例。测试结果与现场部署证据见 tasks.md。发布回执 deployment_id 是异步状态追踪依据，上传成功不能报告已上线。

### 镜像预检日志与 CI 验证

Kubernetes 的 image-check Pod 已是冻结模板的一部分，KubernetesClient.logs 必须允许这一固定容器名，否则真实预检读取结果被 k8s_log_container_invalid 拒绝。本轮修复该白名单，并将既有 runtime-manager 测试替身适配 authorize_step/preflight、协议 v2 对账和只读 Pod 日志语义；原安全断言保持，新增镜像检查 Pod 单独计数。

## 8. 后续边界

真实 Desktop 双用户创建、构建、审批、上线、业务协作和长时间后台运行仍需匹配版本环境验证；单元测试不替代这些验收。Kubernetes、多实例业务数据库及 CRDT 另行设计。

## 修订历史

| 日期 | 改动 | 原因 |
| --- | --- | --- |
| 2026-11-09 | 补齐已实现契约、决策、失败恢复和验证边界 | PR #2595 合入前评审要求及用户修复授权 |
