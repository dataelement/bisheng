# Tasks: MinerU 4.0 独立解析提供方

**关联规格**：[spec.md](./spec.md) · **设计**：[design.md](./design.md) · **版本**：v3.0.0

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户已确认 |
| design.md | ✅ 已评审 | 用户已确认，含 `request_kwargs` 决策 |
| tasks.md | ✅ 已拆解 | SDD tasks 清单评审：LGTM |
| 实现 | ✅ 代码完成 | 14 / 14 完成；目标服务与页面验收待执行 |

## 开发模式

后端按测试先行；各 Wave 内只在依赖满足后实施。真实 MinerU 服务未提供，协议测试使用离线 HTTP/ZIP 夹具；真实服务验收结论单独记录。新增测试放在 `src/backend/test/knowledge/`。本期不新增数据库表或错误码，复用现有知识文件失败状态与错误处理。

## Wave 1：配置与现有路由

- [x] **T001 配置模型与默认示例（基础设施）**
  **文件**：`src/backend/bisheng/core/config/settings.py`、`src/backend/bisheng/initdb_config.yaml`
  **逻辑**：增加独立 `MineruV4Conf`、默认未启用的配置块、`request_kwargs` 映射校验及解析服务参数；`KnowledgeConfig` 声明 `mineru_v4` 的图片能力，旧 `mineru` 与默认 `etl4lm` 保持行为。额外参数只作创建任务顶层 JSON 字段，保留键冲突报错；API Key 仅配置环境变量名。见 design §3 决策 1、6。
  **依赖**：无。

- [x] **T002 OFD 专用队列路由测试（测试）**
  **文件**：`src/backend/test/knowledge/test_decide_queue.py`
  **逻辑**：验证 OFD 与 PDF 在专用队列开启且外部提供方有效时同路由；关闭队列或外部配置缺失时落普通知识队列；包含 `mineru_v4`。不改变队列消息的 tenant_id headers → Worker ContextVar 契约。
  **覆盖 AC**：AC-09。
  **依赖**：T001。

- [x] **T003 OFD 专用队列路由实现（Worker）**
  **文件**：`src/backend/bisheng/worker/knowledge/scheduler.py`
  **逻辑**：`needs_ocr_queue()` 将 OFD 与 PDF 同列；仅判断队列配置及解析能力，不在 scheduler 固定最终 Loader。保持既有 Celery tenant_id headers → Worker ContextVar 传递方式。当前分支已做该定向修复，复核后打勾。
  **依赖**：T002。

## Wave 2：MinerU V1 协议与结果适配

- [x] **T004 V1 HTTP 客户端协议测试（测试）**
  **文件**：`src/backend/test/knowledge/test_mineru_v4_client.py`
  **逻辑**：以 HTTP mock 覆盖秒传/上传完成/轮询/下载、跨源上传和跳转不泄露 Bearer Key、失败终态/超时、`request_kwargs` 只进建任务 JSON 且保留键冲突失败；不连固定内网地址。
  **覆盖 AC**：AC-01, AC-06, AC-10。
  **依赖**：T001。

- [x] **T005 V1 HTTP 客户端实现（实现）**
  **文件**：`src/backend/bisheng/knowledge/rag/pipeline/loader/mineru_v4_client.py`
  **逻辑**：`httpx` 客户端执行 `/v1/uploads`、字节上传/完成、`POST /v1/parse/jobs`、轮询、下载 ZIP；按源控制认证，校验响应与状态并施加阶段/总超时。`request_kwargs` 仅合入建任务 JSON，不承载传输参数。详见 design §3 决策 2、6。
  **依赖**：T004。

- [x] **T006 Middle JSON/ZIP 适配测试（测试）**
  **文件**：`src/backend/test/knowledge/test_mineru_v4_loader.py`
  **逻辑**：离线 ZIP 夹具覆盖 0 基页序、文本/标题/表格/公式/图片、bbox、最终正文 indexes、安全解包、缺图片/错误 schema/partial 失败；检查旧 `enable_formula` 不伪装成 V1 开关。
  **覆盖 AC**：AC-04, AC-05, AC-06。
  **依赖**：T005。

- [x] **T007 Middle JSON/ZIP Loader 实现（实现）**
  **文件**：`src/backend/bisheng/knowledge/rag/pipeline/loader/mineru_v4.py`
  **逻辑**：调用 T005 客户端，把 ZIP 内 Middle JSON 和图片转成现有 `Document`、`bbox_list`、平铺 `local_image_dir`、`preview_file_path` 契约；安全解包、按完整子目录路径替换图片最终 URL 后再计算 indexes；`retain_images=0` 时不暂存图片或生成失效引用；不复用旧 `pdf_info` 结构，不写跨节点本地状态。见 design §3 决策 3、§4.2。
  **依赖**：T006。

## Wave 3：管线、预览与引用

- [x] **T008 提供方选择与旧版兼容测试（测试）**
  **文件**：`src/backend/test/knowledge/test_mineru_v4_pipeline.py`
  **逻辑**：验证显式选择新/旧提供方、未启用保持默认、配置无效不静默退回、本次执行读取全局配置、PDF/图片/OFD 共用选择入口；预览缓存命中沿用已见正文。使用 mock 配置/Loader，不依赖中间件。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-08, AC-10, AC-11。
  **依赖**：T007。

- [x] **T009 提供方接线实现（实现）**
  **文件**：`src/backend/bisheng/knowledge/rag/base_file_pipeline.py`、`src/backend/bisheng/knowledge/domain/models/knowledge_file.py`
  **逻辑**：新增 `ParseType.MINERU_V4`；在唯一 PDF Loader 选择入口构建 T007 Loader，并确保其图片/OFD 委托路径一致。仅在新提供方显式选择时失败即报错，旧版及其他提供方保持原行为；DB 文件记录新解析来源。
  **依赖**：T008。

- [x] **T010 平台引用 API 映射（Platform）**
  **文件**：`src/frontend/platform/src/controllers/API/index.ts`、`src/frontend/platform/src/pages/ChatAppPage/components/FileViewPanne.tsx`
  **逻辑**：让旧 `mineru` 和新 `mineru_v4` 引用与已有新版预览同样得到可用 `fileUrl`；不改变视觉样式。修改前读取 `src/frontend/packages/ui/docs/` 与平台 AGENTS；若触及遗留中文，按 i18n 规则提取。
  **覆盖 AC**：AC-07。
  **手动验证**：在平台聊天打开新、旧 MinerU 文件引用，确认文件预览 URL 和定位可用。
  **依赖**：T009。

- [x] **T011 平台知识页引用处理（Platform）**
  **文件**：`src/frontend/platform/src/pages/KnowledgePage/components/ParagraphEdit.tsx`、`src/frontend/platform/src/pages/KnowledgePage/components/Paragraphs.tsx`
  **逻辑**：统一旧/新 MinerU 的预览类型判断，保障知识分块引用和段落编辑预览；不改变 UI 视觉规范，按现有 i18n 规则处理触及文件。
  **覆盖 AC**：AC-07。
  **手动验证**：打开两类文件的知识分块和段落编辑，检查预览/定位与图片链接。
  **依赖**：T009。

- [x] **T012 客户端聊天引用映射（Client）**
  **文件**：`src/frontend/client/src/api/apps.ts`、`src/frontend/client/src/components/PreviewFile/index.tsx`
  **逻辑**：为旧 `mineru` 与新 `mineru_v4` 生成现有文件预览 URL；遵循客户端 AGENTS 与 UI docs，不改 UI 样式。
  **覆盖 AC**：AC-07。
  **手动验证**：在 `/workspace` 打开两类文件的聊天引用，确认文件 URL、正文和可用定位。
  **依赖**：T009。

## Wave 4：端到端验证与评审

- [x] **T013 E2E 覆盖（测试）**
  **文件**：`src/backend/test/knowledge/test_mineru_v4_e2e.py`
  **逻辑**：按 `/e2e-test` 工作流编写 API 端到端覆盖与页面手动清单；有目标服务时验证 PDF/图片/OFD 的预览、入库终态、图片及引用，无服务时用协议夹具验证可运行部分并记录真实服务缺口。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11。
  **依赖**：T009, T010, T011, T012。

- [x] **T014 特性级代码评审与交付核对（评审）**
  **文件**：`features/v3.0.0/076-mineru-v4/design.md`、`features/v3.0.0/076-mineru-v4/tasks.md`
  **逻辑**：逐任务执行 `/task-review` 并记录完成；运行 arch guard、Ruff、定向 pytest、前端 lint/typecheck，再 `/code-review --base feat/3.0.0`，核对 AC 与设计偏差；未提供服务时如实标注环境验收未完成。
  **依赖**：T013。

## 实际偏差记录

- 离线集成测试放在 `test/knowledge/`，覆盖 V1 协议到 `Document`；无目标服务与毕昇中间件，真实 API/页面验收记录于 `e2e-checklist.md`。
- 前端 typecheck 通过；全量 lint 命中本分支已有的 Platform 93 项、Client 21 项遗留报错，未修改 suppressions。

## 实施与评审结果

- T001–T013 按 `/task-review` 清单检查了任务文件、依赖、分层、密钥/日志、设计同步和前端约定；未发现新增高严重度问题。T014 按 `/code-review --base feat/3.0.0` 的七个维度核对，结果 `PASS_WITH_WARNINGS`：目标服务与 UI 验收尚未执行；全量 lint 受基线遗留报错阻塞。
- 后端定向测试 44 项通过；新代码 Ruff 通过，全部涉及的 Python 文件以 `--ignore RUF013` 检查通过（旧模型文件有既存 RUF013）；`scripts/arch-guard.sh` 通过；前端 `pnpm typecheck`、`pnpm check-i18n` 通过。Platform 三个修改的预览组件、Client 两个修改文件的定向 ESLint 通过。
- E2E 离线测试覆盖 V1 HTTP → ZIP → `Document` 的 PDF/PNG 主链路，OFD 选择及队列由定向测试覆盖。真实服务的 PDF/图片/OFD 预览、入库和引用步骤在 [e2e-checklist.md](./e2e-checklist.md) 中待执行。
- MinerU 4.0 评审提出的两项图片问题已修复：关闭 `retain_images` 时不生成未上传引用，带子目录的图片引用按完整路径匹配；对应定向测试和设计文档已同步。
