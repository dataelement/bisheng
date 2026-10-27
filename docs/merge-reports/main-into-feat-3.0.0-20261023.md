# main 合入 feat/3.0.0：改动与影响范围

日期：2026-10-23。此报告基于本次实际合并差异、代码调用路径和本地验证，不把历史 feature 文档作为已交付证明。

## 合并基线与交付状态

| 项目 | 内容 |
|---|---|
| 目标分支原提交 | `feat/3.0.0` / `38395b19804effe7a8474809f54f5f7396e5b940` |
| 来源分支 | `origin/main` / `83aa354034c14c913800f821074bad8f0c29e1e0` |
| 来源版本 | `3.0.0-beta6`；目标原版本为 `3.0.0-beta4` |
| 来源新增历史 | 35 个目标分支尚未包含的提交（含合并提交） |
| 合并方式 | 保留双方历史的 merge commit |
| 远端复核 | 合并落地前再次查询，main 和目标远端均未变化 |
| 交付边界 | 本地合入 feat/3.0.0；本次未推送、未部署、未执行运维回填 |
| 工作区保护 | 原有脚本 README 修改及两个未跟踪文件保留，不纳入合并提交 |

## 差异统计

相对合并前 `38395b198` 共 390 个文件（包含本报告）。

| 范围 | 文件数 |
|---|---:|
| 发布脚本及 compose | 2 |
| docs | 3 |
| features | 62 |
| src/backend | 240 |
| src/frontend/client | 4 |
| src/frontend/packages | 3 |
| src/frontend/platform | 76 |

精确清单可执行 `git diff --name-status 38395b198 HEAD` 查看；原有未提交文件不在该范围内。

## 主要改动与业务影响

| 范围 | 实际改动 | 影响对象与关注点 |
|---|---|---|
| DSH 身份与准入 | Python 本地持有授权请求、会话和凭证；增加桌面本地认证及旧路径兼容；移除 DSH 对 Gateway 商业 License、人数和席位准入的运行时依赖 | 桌面登录、刷新、退出与模型访问。原 Gateway 会话需要重新登录；平台用户状态、租户及模型授权仍生效。不能据此认定整个平台商业版 Gateway 都已移除 |
| 部门及个人额度 | 采用个人额度优先、未配置时继承部门的路径；前端删除席位重新授权及商业 License/席位管理入口 | DSH 管理员授权、额度继承、用量及操作恢复；原用量、UNKNOWN 和审计证据继续保留 |
| 模型协议 | 增加企业模型协议、推理参数及原生 Responses 支持，复用 provider Token 参数兼容处理 | DSH Chat/Responses、流式输出、工具调用及模型 Token 计量；实际供应商和部署模型需另行验收 |
| 模型审计 | 增加设置、请求元数据/正文、会话与树结构、标题等模型和查询；增加后台写入、状态收敛与树准备任务；管理端提供审计模式、筛选、分组、原文与失败状态 | DSH 请求链、Celery/Beat、SQL、Redis、对象存储及审计管理员。正文模式涉及内容保存、密钥可用性、容量和读取权限，应按实际配置验收 |
| 保存工具调用 | 按名称解析现有保存工具，校验嵌套输入；引入受限 OpenAPI 执行及 JSON 解析边界，不再要求另行发布才暴露保存工具 | DSH 桌面调用及共享工具执行入口。重点回归权限、重名、schema、超时、响应体大小和错误状态 |
| 插件与工作台市场 | 增加工作台上传、目录和安装策略；插件支持 zip/tgz/tar.gz；移除签名租约相关流程 | 企业管理员导入及桌面安装链。新租户第三方插件/工作台安装默认关闭，已有租户选择不因默认值迁移被重置 |
| 前端公共请求 | 导出共享响应/错误处理和认证头，供审计流式请求复用 | 保留 feat/3.0.0 的 F088 ApiError 完整拒绝语义、全局登录/权限处理及共享 notification，避免 main 的旧错误吞噬行为覆盖发布线 |
| 非 DSH 公共后端 | 租户过滤器注册新增模型；公共 LLM 构造时剔除能力声明 reasoning_efforts；工具工厂可注入；HTTP 异常保留结构化 code；用户资料不再投递旧远端同步意图 | 公共请求、用户资料、租户隔离、模型初始化与工具执行均有间接影响，不能将本次范围理解为只改 DSH 页面 |
| 信息源查询 | 保留来源分支 return_information 参数修复，整合目标分支已有快照边界测试 | 最终信息源客户端相对合并前目标分支无净代码变更；测试同时覆盖 return_information 和 max_create_time，未退回旧同步快照行为 |
| 发布与依赖 | 前后端版本、compose 镜像和 update.sh 更新至 beta6；声明 jsonschema==4.25.1 | 后续使用默认 compose/update 脚本将选择 beta6 镜像。本次没有构建、拉取或部署镜像；保留目标分支 React Query 4.44.0 和现有依赖架构 |

主要实现入口：`src/backend/bisheng/dsh/`、`src/backend/bisheng/dsh_market/`、`src/backend/bisheng/tool/domain/services/`、`src/frontend/platform/src/pages/SystemPage/dsh/`、`src/frontend/platform/src/pages/BuildPage/dsh/`、`src/frontend/platform/src/controllers/request{,Stream}.ts`。

## 冲突与合并补充修复

本次 Git 报告 14 个冲突文件。采用逐项整合，未整文件用另一侧覆盖语言资源或业务逻辑：

- `release-contract.md`：保留发布线已有 F076/F077/F078/F085/F086/F087/F088 内容，补入 main 的 DSH 本地接入约束。
- 信息源测试：同时保留两种 return_information 的参数化验证和目标分支 max_create_time/快照断言。
- 请求模块：保留 F088 错误对象、错误提示去重、登录和权限行为；补入 main 的流式复用出口及 Bearer 认证头。
- 部门额度、DSH 管理页：应用 main 去席位化及模型审计入口，保留目标分支共享组件。
- 插件市场：保留共享 UI，接入工作台页签、安装策略和 npm 包格式。
- 删除已由 main 移除的席位/License 组件及对应测试，不重新连接被移除的产品入口。
- ESLint 抑制文件保留双方自动合并内容、冲突处保留发布线较小计数，并运行 lint:prune；最终相对合并前无净变化。
- 自动合并之外，修复 main 新增页面指向已删除旧 Button/Input/Toast/Badge 等组件入口的引用，统一使用已落地的共享组件；相关测试匹配共享组件的 aria-disabled 与真实指针交互。

## 数据库与升级影响

传入 main 的两条迁移：

1. `f065_dsh_install_policy_default_off`：只更改安装策略字段的数据库默认值，已有租户的值保持原样。
2. `work110_dsh_local_sessions`：既有 dsh_model_call 的 seat_id/grant_version 允许为空，并调整版本检查约束；不清除历史调用记录。

目标分支原有两个迁移 head，合并 main 后成为三个。新增 `v3_0_0_merge_main_work110_release300.py`，将 `asr_rt_model_type`、`merge_skill_center_heads`、`work110_dsh_local_sessions` 汇成 `merge_main_work110_release300` 单一 head。该合并迁移 upgrade/downgrade 均无操作，未改写已发布迁移的父子关系，未执行数据修复。

新会话及审计整表由项目现有模型发现/create_all 启动路径创建。历史审计名称、展示状态和树结构有独立运维脚本；部署后如需完整历史检索，应逐租户预览后按运维流程执行：`backfill_dsh_audit_model_names.py`、`backfill_dsh_audit_presentation.py`、`prepare_dsh_audit_tree.py`。本次仅合并文件，没有运行这些脚本。

## 验证结果与证据边界

| 检查 | 结果 |
|---|---|
| 前端 DSH、市场、统一请求及流式请求 | 36 个文件、302 个用例通过 |
| 后端 DSH 本地用例 | 654 passed、110 skipped、63 deselected；显式排除外部数据库/Redis用例及已定位的批量测试状态问题 |
| 市场及保存工具专项 | 191 passed、1 deselected；排除本地 MCP 依赖不匹配导致的启动用例 |
| 模型协议、本地认证及工具 HTTP 专项 | 124 passed、1 skipped |
| 信息源、迁移图和本地会话专项 | 29 passed、1 skipped；包括单 head 和既有 main 迁移文件逐字节不变检查 |
| 本次前端整合文件 ESLint | 23 个文件通过 |
| 三语及错误码 | pnpm check-i18n、pnpm --filter @bisheng/locales check 均通过 |
| 架构守卫 | 无 VIOLATION；6 个传入测试/fixture 文件触发 RULE-7 模式警告 |
| 全量 pnpm lint | 未通过：85 个错误；在合并前 38395b198 的主工作区运行得到相同 85 个错误 |
| 全量 pnpm typecheck | 未通过：缺少本地 @hello-pangea/dnd 安装、clientVoiceDraft.test.tsx 参数个数错误；以相同依赖运行合并前提交，复现相同 2 项错误 |

全量后端首次运行并非全绿：955 passed、117 skipped、54 个隔离外部服务配置错误，以及 3 个失败。其一是合并后多 head，已修复并通过专项；其二是本地 MCP 库不接受 max_request_body_size；其三是 native_access 的租户隔离用例在批量进程内失败，该用例在原始 main 批量测试亦复现、独立及协议专项通过。按模块拆分后取得上表结果，未把批量失败记为通过。另一次宽范围排除运行出现跨测试租户 ContextVar 污染，不作为业务行为验收证据。

未运行生产部署、MySQL/DM8 升级回放、真实 Redis/MinIO/OpenFGA 多租户 E2E、真实桌面客户端和供应商模型联调；本地测试不能替代这些环境的验收。合并完成不代表已达到发版验收条件。

## 建议后续验收重点

1. 部署前修复既有 lint/typecheck 基线；在 MySQL、DM8 验证升级至唯一 head、旧调用证据及额度保持。
2. 真实桌面验证旧会话重新登录、本地刷新/退出、账号禁用、租户切换及非管理员模型授权。
3. 验证审计 OFF/METADATA/CONTENT、失败/超时/取消、原文权限、密钥缺失、后台队列和历史准备状态。
4. 验证企业 Chat/Responses 推理参数、Token 结算、嵌套保存工具输入与第三方安装默认关闭。
5. 对公共 LLM 初始化、用户资料更新和信息源快照同步做部署后回归。
