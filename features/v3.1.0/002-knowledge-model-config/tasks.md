# Tasks: 知识模型配置收敛

## 状态

| 文档 | 状态 |
| --- | --- |
| 需求发现 | ✅ 用户确认，历史旧溯源读取保留 |
| spec.md | ✅ 已评审且用户确认（2026-11-27） |
| design.md | ✅ 已评审且用户确认（2026-11-27） |
| test-cases.md | ✅ 15 条 QA 参考用例，八列检查通过，未执行 |
| tasks.md | ✅ 已拆解并自审通过 |

独立分支 `codex/knowledge-model-config-20261127`，基线 `49dde8a70d`。只在此工作区修改，不对共享工作树执行 stash、reset、clean 或全局 restore。无数据库 schema 变更，无迁移或回滚脚本。Client 无需实现改动。

## Wave 1：默认配置与空间创建

- [x] **T001（基础设施）**：准备本地依赖与基线验证。复用后端现有 venv，前端按锁文件安装到独立工作区；不修改依赖版本。记录相同测试选择的基线，确保区分原有失败。无业务配置写入。
- [x] **T002（测试）**：扩展 `src/backend/test/knowledge_unification/test_kn_creation_settings.py`、`test_kn_creation.py`、`test_kn_creation_api.py`、`src/backend/test/llm/` 的默认消费者/自动补齐/保存测试及相关默认配置/提取回归；验证知识 A / 旧工作台 B 来源分歧、显式 C 优先、缺失/失效与租户共享拒绝、退役槽位被忽略、保存不改既有空间。配对 T003，依赖 T001。覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-16。
- [x] **T003（后端 Domain / API）**：删除 `llm/domain/schemas.py` 两字段及 `default_reference_extractor.py`、`system_model_autofill.py` 对应注册；简化 `model_default.py` / `llm.py` 保存探测；`creation_settings.py` 保持原响应，默认 ID 投影为字符串且名称为空；`knowledge_space_service.py` 默认读取知识单槽位，最终缺失报 10901，授权对象查询仅移除模型前置检查；`legacy_documents.py` 沿用知识错误。保留原身份、配额、事务、模型准入与引用同步。依赖 T002。

## Wave 2：旧溯源生成退出与历史读取

- [x] **T004（测试）**：在 `src/backend/test/workflow/` 扩展 callback 回归，覆盖输出/流式结束/选择/输入、新引用持久化与 source=0、无旧任务；复用 `test/knowledge/test_qa_recall_repository.py`、`test_qa_recall_authorization.py` 验证旧数据可读及非管理员拒绝。同步删除 `src/backend/test/dsh/test_billing_scope.py` 中只测试退役生成 getter 的两个用例；其他计费逻辑不改。配对 T005，依赖 T001。覆盖 AC: AC-10, AC-11, AC-12, AC-13, AC-14, AC-15。
- [x] **T005（Worker / 后端 Domain）**：在 `worker/workflow/redis_callback.py` 停止旧关键词任务并将新文件来源映射为 source=0，QA/链接/无权限类型保持；删除 `common/chat/utils.py` / `__init__.py` 生成函数和 prompt、`llm.py` 溯源 getter、`workstation/.../chat_helpers.py` 旧生成路径。保留新引用注册与存储、旧读取 API、Repository、表及前端入口；不新增 Worker 任务，原 Celery headers → tenant ContextVar 机制保持。依赖 T003、T004。

## Wave 3：Platform 设置与三语文案

- [x] **T006（测试 / Frontend Platform）**：扩展 `ModelPage/manage/tabs` 表单回归，验证无退役字段、无旧必填或重建确认、单提示词保存不带旧设置；保留旧弹窗和新引用组件回归。依赖 T001。覆盖 AC: AC-01, AC-08, AC-09, AC-10, AC-12, AC-13, AC-14, AC-16。
- [x] **T007（Frontend Platform）**：更新 `WorkbenchModel.tsx`、`KnowledgeModel.tsx`、`knowledgeModelValidation.ts` 及实际调用到的校验辅助；删除退役值在载入、草稿、整表/提示词保存中的传递；新增默认 embedding 提示。修改 `public/locales/{zh-Hans,en-US,ja}/model.json` 及共享 `packages/locales/src/api_errors` 的 10901 三语说明；不手改生成文件，不删除历史旧弹窗文案/路由。依赖 T003、T006。

## Wave 4：验证、审查与交付

- [x] **T008（测试）**：组合执行默认模型、空间创建、配置保存、QA、callback、新引用和历史读取测试；运行受影响 Platform lint / typecheck、i18n 与变更 Python ruff / arch-guard。生成 `/e2e-test` 所要求的 API 覆盖与 UI 清单；真实环境未提供时明确标记未执行，局部 HTTP/SQL 链路仍须执行。依赖 T005、T007。覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16。
- [ ] **T009（审查 / 文档）**：各任务按 `/task-review` 记录，更新 design 当前实现、偏差和验证限制；执行 `/sdd-code-review --base origin/feat/3.1.0`。提交本分支的已完成代码与文档供审查，不自动部署或合并。依赖 T008。

## 实际偏差记录

T003 初值读取只投影 embedding 的原始标量，避免无关坏配置阻断修复或布尔值被转成模型 1；见 design.md §4.1，未改变已确认需求。

T008 完成可执行的本地 HTTP/SQL 和组件验证；真实环境/浏览器验收未提供，E2E 报告标 PARTIAL，见 verification.md。
