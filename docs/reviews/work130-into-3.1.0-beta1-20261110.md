# work-130 合入 3.1.0-beta1：独有改动与影响范围

核查日期：2026-11-10。按用户要求，完整合并 `feat/bisheng-work-130` 到 `feat/3.1.0-beta1` 并推送远端。

## 比较口径

- 合并前目标：`918813fd25f79627e8fcb4322c3938adbccd95c1`。
- 合并源：`83b98d2838dddbd997b61b5fdcc30b1bbf92b017`。
- 共同祖先：`9fe40a4f21753f792a363ad1294eb79b405747ca`。
- 源分支有 18 个目标分支尚未包含的提交，含功能、修复、合并和交付文档提交，不能解读为 18 项独立功能。
- 下表按合并结果相对目标的实际增量整理；不是两分支树之间的直接差异，后者会把 3.1 已有功能误算为删除。
- 合并结果涉及 163 个文件（不含本报告），其中 43 个测试文件；新增迁移汇合文件计入后端。

## work-130 特有的主要增量

| 主题 | 实际新增行为 | 合并后的影响范围 |
| --- | --- | --- |
| 桌面令牌刷新恢复 | 刷新响应丢失时，在宽限条件内返回同一个后继令牌；已消费令牌的恢复还要求后继未使用，避免无限重放。新增 `refresh_reuse_grace_seconds`，默认 86400 秒，0 为严格重放撤销 | DSH 本地登录、刷新、设备会话、签名密钥派生。主要对应 `3494a7339f`、`0b2845d074` |
| 按业务活动续期 | 新桌面会话使用 `SLIDING_IDLE_V1`，默认 14 天无业务活动过期；刷新、鉴权、轮询不续期。有效业务请求续期，失效或撤销的会话不恢复 | DSH 模型/工具调用、工作流输入、工作台日常聊天和任务提交，以及 Web 会话身份适配。对应 `f173bc70d8` |
| 云端工作台桌面接入 | 增加桌面应用目录、一次性启动票据、限定应用的会话、源码导出及发布适配；复用既有应用权限和发布链路 | `app_runtime`、`app_publish`、DSH `/dsh/apps`、内部 app-proxy RPC。目录分页与使用/编辑权限检查会影响桌面应用发现和发布。主要对应 PR #2595 |
| 网页云端工作台入口 | 客户端应用页和管理端构建页增加统一入口；客户端新增 `/apps/cloud-workbenches`，调用 `/api/v1/apps/workbenches` | client、platform、三语言共享文案和应用卡片；保留 3.1 新版布局、插件权限门禁及环境同步 |
| 应用代理安全边界 | 启动票据兑换为应用专属 Cookie；转发时剥离平台应用会话 Cookie；SSE 流持续复核身份/授权 | `src/app-proxy` 的认证、请求头、反向代理及事件流；需发布对应代理镜像才能获得这些行为 |
| 桌面消息赞踩审计 | 桌面消息评价单独持久化，审计会话显示数量及详情；支持修改、撤销、乱序和幂等。撤销水位阻止旧评价重放后复活 | `/api/v1/dsh/audit/message-feedback`、DSH 能力声明、审计列表/详情/树、platform 模型审计 UI。主要对应 PR #2646 |
| 在线开发指南与 SDK | 新增中英文工作台指南、SDK 0.1.2 wheel 和发布清单；SDK 增加共享记录、版本冲突、操作幂等、事件订阅/回放能力 | `dev_toolkit`、SDK 发行及打包脚本。原 0.1.1 发行物保留；指南/SDK 分发仍受 `open_platform.enabled` 控制 |
| 运行时测试适配 | 更新授权步骤、v2 执行/恢复、Helm API 发现及日志模板等测试替身和断言 | 相对本次目标，runtime-manager 的增量全部位于 12 个测试文件；`image-check` 日志白名单修复已存在于目标分支，没有重复引入生产逻辑改动 |

## 模块覆盖

| 路径 | 文件数，不含本报告 | 关注点 |
| --- | ---: | --- |
| `src/backend` | 89 | 身份、业务活动续期、审计、云端应用、发布、分发、迁移及测试 |
| `src/frontend/client` | 10 | 云端工作台目录、入口、路由及文案生成物 |
| `src/frontend/platform` | 12 | 构建页入口、模型审计、类型和文案 |
| `src/frontend/packages` | 3 | 三语言共享文案源 |
| `src/app-proxy` | 10 | 桌面启动、Cookie、SSE 与测试 |
| `src/bisheng-sdk` | 9 | 0.1.2、协作模块、锁文件和测试 |
| `src/runtime-manager` | 12 | 测试适配 |
| `features/v3.0.0` | 17 | 会话、云端工作台、消息评价契约及交付记录 |
| `scripts/pack_sdk_wheel.sh` | 1 | SDK 多版本发行包处理 |

## 数据库和部署影响

1. DSH 刷新令牌增加 `used_at`；会话增加 `expiry_policy`、`last_activity_at`、`idle_ttl_seconds`，并增加刷新令牌活动索引。
2. 新增 `dsh_model_audit_message_feedback` 与 `dsh_model_audit_feedback_retraction` 两张模型发现表，分别保存有效评价与撤销顺序水位，沿用租户隔离。
3. 已存在的 `runtime_artifact.size_bytes`、`runtime_transfer.offset` 从整数拓宽到 BigInteger，迁移允许模型已建表/列的情况。
4. 两条分支分别拥有迁移头 `v310b1_f004_workflow_soft_delete` 和 `f130_cloud_workbenches`。新增 `v310b1_merge_work130_heads` 汇合；无 DDL/DML，不修改任何已发布修订的父节点。最终单头检查通过。
5. 新桌面会话默认空闲期为 14 天；旧绝对期限会话默认不转换。`session_idle_migrate_existing` 默认为 false，开启后也只转换仍有效且发生业务活动的会话。
6. 合并不自动开启托管运行时或开发工具分发配置。完整云端工作台上线需要既有运行时、代理、公开入口及相应功能开关；仅更新后端不能代表桌面发布链路完整可用。
7. 本次交付范围是代码合并与推送，没有执行 109 的重新部署。此前 109 的 `open_platform.enabled` / `app_runtime.enabled` 为 false；实际部署时应重新核对环境配置、备份数据库并执行迁移。

## 冲突与集成处理

- `client/src/pages/apps/index.tsx`：保留 3.1 的模块布局、介绍文案及移动端搜索结构，加入云端工作台入口。
- `client/src/routes/index.tsx`：保留 3.1 的 `ClientEnvironmentSync` 和现有路由树，仅增补云端工作台懒加载路由及权限门禁。
- `runtime-manager/tests/test_k8s_client.py`：保留两边日志模板覆盖，明确 image-check 的临时存储测试值。
- 新增迁移汇合修订，避免 `alembic upgrade head` 因多头而中断。
- 更新新增空闲续期测试的租约替身，使其适配 3.1 的部门执行租约检查；生产租约检查和并发限制保留。
- 3.1 既有“对话项目同步”及桌面环境同步保留。它们本来就属于目标分支，不计为 work-130 的独有新增；这次合并推送本身不会改变 109 当前接口是否可用。

## 本地验证

| 验证项 | 结果 |
| --- | --- |
| 后端反馈、刷新/空闲会话、云端工作台、桌面发布、指南/SDK 分发、3.1 项目同步及迁移单头专项 | 127 passed，2 skipped |
| app-proxy 全套 | 279 passed |
| SDK 全套 | 218 passed |
| runtime-manager 受影响的 11 个测试文件 | 575 passed，4 skipped；Helm 3.19，使用本地假 API，不连接真实集群 |
| client 目录与环境/根路由测试 | 4 个文件，30 passed |
| platform 模型审计测试 | 7 passed |
| 前端工作区 `pnpm typecheck` | 通过 |
| `locales:check`、`check-i18n` | 通过 |
| 本次修改的全部客户端/管理端 TS、TSX 文件 lint | 通过（client 7 个，platform 6 个） |
| 架构守卫相对目标比较 | 8 条已有扫描信息，新增 VIOLATION 为 0 |
| Python 集成修改 Ruff、差异空白和冲突标记检查 | 通过 |

全量 `pnpm lint` 存在目标基线问题：`platform/src/pages/ModelPage/manage/ModelConfig.limit.test.tsx` 第 67、74 行的中文测试字符串触发 `no-restricted-syntax`；该文件与合并前目标完全相同，不在本次增量中。不能把全量 lint 称为通过。

前端测试依赖使用冻结锁文件安装；未构建的可选 canvas 依赖只在隔离工作区取消测试解析链接，未修改依赖声明、锁文件或业务源码。

以上为本地合并验证，不代表远端 CI、真实 MySQL/DM8 升级、双用户桌面发布或 109 部署验收完成。
