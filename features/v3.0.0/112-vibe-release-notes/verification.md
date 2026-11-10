# F112 定向验证记录

日期：2026-10-27。隔离分支：`codex/112-vibe-release-notes`；基线：`feat/3.0.0@e890280afb35cda0d78f6ec06b2e41af6856f7f9`。

## 1. 结论与证据边界

CLI、接收保存、审批快照、正式版本查询、两个 SPA 展示和下载安装件已完成。本地定向检查通过。**真实部署 E2E 尚未执行，T028、T029 未完成，不作为完整 SDD 或已部署验收通过的声明。** 开发阶段没有远端代码更新、DDL、重启、镜像发行、推送或 tag；本次仅按用户后续授权合并推送代码。

后台隔离 API 链路使用实际 HTTP 路由、业务服务、审批引擎和 SQLite；外部编排、对象存储及运行凭据查询使用已有 fixture。它证明字段传递、保存和权限拒绝，不能证明真实 Celery 跨进程、MySQL/DM8 升级或 Docker/K8s 发布。浏览器使用隔离链路导出的测试数据展示实际组件，并非 116 在线界面。

## 2. 执行记录

| 范围 | 实际结果 | 说明 |
|---|---|---|
| 后端新增领域/API/快照测试及相关原有版本、审批、单 head 测试 | 阶段性 62 passed | `/tmp/f112-backend-focused.log`；SQLite，外部服务 fixture |
| 最后一次功能定向集合 | 27 passed，1 skipped | `/tmp/f112-feature-final.log`；skip 为需专用部署环境的真实 E2E，不计通过；后续只补跑新增或修改的测试 |
| 隔离 API 发布→管线→审批→版本→驳回 | 通过 | `test_api_worker_approval_and_version_roundtrip`；普通非 owner、跨租户读取拒绝精确断言 16106、16101、18101；审批决定由已有获权审批 fixture 执行 |
| 实际 CLI 下载接口 | 1 passed | `test_platform_serves_the_actual_release_notes_cli_wheel`；GET 发行元数据和真实 wheel，核对摘要与新命令内容；最终安装件重建后单独执行 |
| CLI 新增定向测试 | 33 passed | 输入、文件错误、能力严格拒绝、空说明兼容、重传冻结、三语言提示及打包 post 基线；已有 deploy/packaging 50 项相关测试也有通过记录，不重复累加为新用例 |
| Platform 两处版本组件 | 4 passed | `/tmp/f112-platform-final.log`；版本绑定、全文/空态、脚本纯文本、切应用过期请求 |
| Client 审批组件 | 12 passed | `/tmp/f112-client-final.log`；task/instance、快照唯一来源、旧空态及原有行为 |
| 新 CLI 安装件 | 通过 | 离线构建并在全新 venv 安装，console version/help；fresh shell 指定 PATH，dry-run 仅凭据读取使用内存 fixture，无网络 |
| 安装件一致性 | 通过 | wheel SHA-256 与 manifest 一致；wheel 中 21 个 Python 源文件与当前源码逐字节一致；SDK manifest 未变 |
| Ruff | 通过 | 从 backend、CLI 各自目录按各自配置检查受影响 Python 文件；另做 F821；未使用全仓检查 |
| 架构守卫 | 通过 | 对 30 个受影响 .py/.ts/.tsx 文件逐一传入真实路径，无发现；不是无参数空运行 |
| ESLint / 类型 | 通过 | 仅受影响文件 ESLint；按项目 TS 配置建立程序，受影响根文件诊断均为 0；**未运行全仓 pnpm typecheck** |
| i18n | 通过 | 三语言 key/错误码漂移检查及生成物 build.mjs --check；没有手改生成产物 |
| 数据库迁移 | 通过 / 静态 | SQLite 实际执行两次 upgrade/downgrade，旧行 NULL；Alembic 单 head；MySQL/DM8 使用既有 LargeText/DDL helpers 静态核对，无真实双库升级 |
| 浏览器布局 | 通过（组件预览） | 1440px 和 500px；多行/长行/脚本字面值/空态；500px 正文宽 404px，不需要横向滚动阅读全文，原表头仍可横向滚动 |

各阶段有重叠用例，表内数字不相加为总用例数。测试不涉及的远端数据库、真实进程重启和部署状态一律不记通过。

### 本地环境适配

- 后端复用已有 Python venv 与忽略的本地配置，不提交配置及凭据。
- 前端复用与基线依赖一致的 node_modules；没有安装或升级依赖。Client 的可选 canvas native 包不可用，用进程级 preload 仅让 jsdom 走其支持的无 canvas 模式；没有更改共享依赖。
- 格式化仅受影响文件，Platform 与 Client 保留各自分号约定。测试运行有既有第三方弃用告警，没有为本功能屏蔽业务断言。

## 3. AC 追溯

以下“通过”均指列明的本地层次；真实部署要求仍见第 5 节。

| AC | 证据 | 本地结论 |
|---|---|---|
| AC-01 | CLI 文件/文本上传测试、API 可选 form | 通过 |
| AC-02 | CLI 互斥参数测试，上传调用次数为零 | 通过 |
| AC-03 | 两个 Python 模块共用相同测试向量，CRLF/CR/首尾及内部缩进 | 通过 |
| AC-04 | 2000/2001 码点含 emoji，CLI 与 backend 均拒绝超限且不截断 | 通过 |
| AC-05 | 不存在/目录/不可读/非法 UTF-8；相对 cwd | 通过 |
| AC-06 | dry-run 本地校验，无 HTTP；安装 wheel 单独烟测 | 通过 |
| AC-07 | 直接 HTTP 400 + 16233，创建/存储/入队之前校验 | 通过 |
| AC-08 | 新 session 重载与实际 run_pipeline；CLI 重传不重读文件 | 通过；真实跨进程/重启未实测 |
| AC-09 | 后续版本不覆盖旧值，API/快照内容一致，无编辑入口 | 通过 |
| AC-10 | rejected/withdrawn/online 快照及版本测试；HTTP 实际驳回后 GET | 通过；真实部署待执行 |
| AC-11 | 校验拒绝无正式版本，原管线失败与版本生成顺序保持 | 通过 |
| AC-12 | 实际审批详情/审批任务 GET、Client 组件 task/instance | 通过；在线 UI 待执行 |
| AC-13 | 版本映射与两处组件绑定，刷新/切应用响应隔离 | 通过；在线 UI 待执行 |
| AC-14 | 迁移旧行 NULL、缺字段/None 组件空态 | 通过 |
| AC-15 | 三语言、纯文本、实际组件 1440/500px | 通过（组件预览） |
| AC-16 | 原 scope、owner/普通非 owner/跨租户拒绝；审批拒绝精确码 | 通过（隔离 API）；真实身份配对待执行 |
| AC-17 | 可选字段与旧空值，CLI 不带说明软能力检查，min_compatible=3.0.0 | 通过 |
| AC-18 | 缺能力/错误类型/版本不符/接口失败均不上传；空说明原行为 | 通过 |
| AC-19 | 字段只留平台发布/版本/审批，未传 manager RPC/容器/资源档位 | 静态及平台层通过；不重复 Docker/K8s 全量回归 |
| AC-20 | 实际下载 API + wheel 摘要/源码一致 + 独立安装/fresh shell | 本地通过；在线平台分发待执行 |

## 4. 交付安装件

- CLI：`3.0.0.post1`，`min_compatible=3.0.0`，`platform.version=3.0.0`。
- wheel：`bisheng_cli-3.0.0.post1-py3-none-any.whl`。
- SHA-256：`6a128d56c2bdae6702f0239aa2995920539be121b717561f1e7f4914b8ca4b67`。
- 同时交付模型字段和幂等 migration `f112_release_notes`；原版本 `vibe_merge_release_20261025` 为父 revision。
- 升级必须先增加两列，并让 API 与 Celery 采用同一份代码，再开放带说明发布。仅回滚代码保留 nullable 列；执行 downgrade 会删除说明，须单独备份并确认。

## 5. 待完成的真实验收

已生成 opt-in 用例 `src/backend/test/e2e/test_e2e_vibe_release_notes.py`，配套 [操作清单](./e2e-checklist.md)。需要安装本提交的专用环境、专用 e2e-f112 应用、普通 owner/非 owner/跨租户账号和已指派审批人；仅在内存提供令牌。一次提交→审批决定→版本读取，不跑全量。

116 仅只读盘点：后端当前使用 `cr.dataelem.com/dataelement/bisheng-backend:feat_3.0.0`，已有应用运行，尚未包含本次 F112。不能将本地验证当作该部署已支持说明。本轮未修改远端，需确认合适的测试更新窗口后执行真实 E2E，再完成 T028 与 T029 的正式 L2。

## 6. 合并推送续办

2026-10-27 用户明确要求“提交推送 feat/3.0.0 分支，然后再合并到 release 分支并推送远端”。本次据此先交付代码；真实部署 E2E 及依赖其证据的最终审查继续待完成，不标记通过，不执行 116 更新。

交付源码提交：`ab27c7d385c6bcd99e0908d48b1019574fb4243e`。集成从 `origin/feat/3.0.0@c612d8afbf290ea368315b20b8d9e2b4313f418b` 开始，保留其新增工具、评估修复及环境文档；随后将完成的发版线合入最新 `origin/release`。实际远端 SHA 以本次工具核验及交付回执为准，避免在提交内自引用未知提交 SHA。

本次集成核对：合并无冲突；F112 功能文件与 `ab27c7d38` 无内容差异；16 个变更 JSON 解析、语言生成物检查、逐文件架构守卫、wheel 摘要与源码一致性通过。迁移图定向测试 1 passed；首次普通 pytest 被隔离工作树缺少本地 config.yaml 的全局 conftest 阻断，随后对该纯离线图测试使用 `--confcutdir=test/database` 排除无关全局初始化并通过，未注入或复制部署凭据。未运行全量或远端验收。
