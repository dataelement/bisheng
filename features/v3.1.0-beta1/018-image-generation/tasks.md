# 通用图像生成：执行计划

规格、简化设计均已于 2026-11-09 获用户确认。按 sdd-review 任务清单自查：依赖和 AC 追溯完整；无新数据库对象。测试与实现分开记录，所有新增后端测试集中一个文件。

| ID | 类型 | 任务、文件及验收 | 依赖 | 状态 |
|---|---|---|---|---|
| T001 | 基础设施 | 在 `src/backend/bisheng/common/errcode/tool.py` 增加工具配置无效错误，复用工具码段；无 DB 变更或回滚脚本。 | 无 | 完成（本地验证） |
| T002 | 后端测试 | `src/backend/test/tool/test_image_generation.py`：本地 HTTP 验证新旧加载名、地址规范化、模型/提示词、URL/Base64、多图和安全失败；测试先运行记录失败。覆盖 AC: AC-01, AC-02, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11。 | 无 | 完成（本地验证） |
| T003 | 后端实现 | 新 `bisheng_langchain/gpts/tools/image_generation/tool.py` 集中配置、请求、结果；`gpts/load_tools.py` 注册新旧键及 model/上传依赖；删除旧 DALL-E/Azure wrapper。 | T002 | 完成（本地验证） |
| T004 | 后端测试 | 同一个 `test_image_generation.py` 增加保存/掩码/host 切换、无效配置不落库、管理员拒绝、子项脱敏用例。覆盖 AC: AC-04, AC-05, AC-07, AC-12。 | T001, T003 | 完成（本地验证） |
| T005 | 后端实现 | `ToolServices.update_tool_config` 复用 Key 掩码并规范化图像配置；`GptsToolsType.mask_sensitive_data` 掩码历史图像子项。共享逻辑限图像 tool_key。 | T004 | 完成（本地验证） |
| T006 | 后端测试 | 同一个测试文件增加当前调用配置刷新、权限拒绝、租户隔离的上传回调与上传失败场景。覆盖 AC: AC-02, AC-09, AC-11, AC-12。 | T003 | 完成（本地验证） |
| T007 | 后端实现 | 现有 `ToolExecutor` 中接入当前配置及 MinIO 上传回调；同步和异步都用本次局部实例。Worker 继续使用现有 Celery headers→ContextVar，不引入消息字段/秘密。 | T006 | 完成（本地验证） |
| T008 | Platform 实现 | `Dalle3.tsx` 替换为 `ImageGeneration.tsx`，只保留地址/Key/模型/代理，await 保存并保留错误草稿；`sharedSelection.test.tsx` 更新既有测试。 | T005 | 完成（本地验证） |
| T009 | Platform 实现 | `ToolSet.tsx` 与 tools `index.tsx` 按新旧 tool_key 进入同一设置，成功才关闭；其他工具保持回归。 | T008 | 完成（本地验证） |
| T010 | 预置数据 | 两个现有预置种子 JSON 更新通用名称、新工具键；不迁移现有 DB ID。 | T003 | 完成（本地验证） |
| T011 | 共享文案 | `packages/locales/src/tool/` 三语言和 `api_errors/` 三语言更新，运行 locales:build；生成产物同步 Platform/Client，不编辑 Client 业务组件。 | T001, T008 | 完成（本地验证） |
| T012 | 验证 | `/e2e-test` 接口业务场景及页面检查、核心组合回归、lint/typecheck/i18n、架构守卫、特性代码审查；真实上游/MinIO 缺失时记录未验证。 | T007, T009, T010, T011 | 本地完成；真实服务/页面验收待环境 |

## 实际偏差记录

- 用户明确移除 Azure；规格删除 AC-03、修订 AC-07，简化设计已确认。

## 执行与审查证据（2026-11-09）

- T002/T004/T006 实现前分别运行失败，记录于 `/tmp/image-generation-{red,settings-red,executor-red}.log`；实现后核心 11 个用例通过。
- T004 改为真实 ASGI 路由 → Service → SQLite DAO 的业务场景；保存不请求上游，失效输入/普通用户/跨租户均不覆盖已存配置。
- T001–T011 按 task-review 清单核对 AC、分层、权限、脱敏和依赖，代码及本地自动验证完成。
- T012 证据及实际环境限制见 [verification-local.md](./verification-local.md)。无真实模型/MinIO/页面联调结果，不以本地替身作为发布验收。
