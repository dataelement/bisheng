# 本地验证记录

- 日期：2026-11-27。
- 开发分支：`codex/knowledge-model-config-20261127`；代码基线 `49dde8a70d`。
- 对照工作区：`/private/tmp/bisheng-model-config-baseline-20261127`，相同提交、相同后端 venv、相同配置；前端复用相同依赖目录，使用各自源码与测试配置。
- 运行时：Python 3.11.13，pnpm 9.15.9，Vitest 3.2.7。无依赖版本或锁文件修改。
- 实际执行的是本地 HTTP/SQL 链路、业务与组件测试。权限/模型/中间件部分使用现有 fixtures 替身，不等同真实部署或浏览器验收。

## 结果

| 检查 | 结果 |
| --- | --- |
| 首组原始后端基线 | 68 passed |
| 核心后端组合回归（默认值、表单配置、继承准入、历史读取与新输出） | 首轮 143 passed；新增场景纳入下方最终组合 |
| 最终后端组合 | 379 passed / 22 failed；失败集合与原始基线完全一致，无新增失败 |
| 对照扩展集合 | 基线和改动后均为 238 passed / 20 failed，失败节点相同 |
| 对照计费集合 | 两边均有相同 2 项原有失败；只测试已退役生成 getter 的 2 个用例随生成函数删除 |
| 核心 Platform 表单、校验与旧弹窗 | 7 个文件 / 27 passed；无未处理异常 |
| 历史 SourceEntry 按钮兼容 | 1 passed；历史 source=1 可触发旧入口，新 source=0 不显示该按钮 |
| 扩展 Platform（含空间创建页面与新引用预览） | 49 passed / 3 failed；在原始源码的同两文件重现同样 3 项失败，另 22 项通过 |
| Platform lint | 通过；1 条已有的 BatchTagDraftDialog 无用 eslint-disable 警告 |
| Platform typecheck | 通过（最终结果在提交前复核） |
| 三语 check-i18n / locales check | 通过，无新增漂移，生成文件与源一致 |
| 改动 Python ruff format / check | 通过 |
| 改动生产 Python arch-guard / git diff --check | 通过 |

## 核心验证内容

1. 初值只读知识默认 ID，不暴露 provider 参数；坏的无关 QA 配置不阻断初值，布尔/对象 ID 不会变成模型 1 或输出凭证。
2. 新建 HTTP 接口 → 实际空间服务 → SQLite 数据，验证知识默认、显式选择、缺失 10901、失败无残留、租户和创建资格约束；旧工作台配置退出默认。
3. 创建授权对象选择不依赖默认模型，仍检查身份与配额；根租户知识 embedding 继承后保持原准入，下线后拒绝。
4. 默认配置保存不读写已有空间或引用，无提供方探测、无重建任务；其他配置校验和事务回滚保持。
5. 工作流普通/流式/选择/输入输出四种路径落库和发送的 source 都为 0，新引用仍保存，不派发旧关键词任务；QA/链接/无权限类型保持。
6. 历史关键词通过真实 HTTP → 服务 → SQLite 读取，移除模型配置后仍可访问；跨用户、跨租户与来源文件权限沿用原测试。
7. 两个退役槽位在 schema、自动补齐、引用提取、表单草稿/整表/提示词保存均退出；真正使用的空间及其他模型槽位保留。

## 组合测试选择

后端在 `src/backend/` 使用 `.venv/bin/python -m pytest <以下路径> -q --disable-warnings --tb=short`：

```text
test/llm/test_knowledge_model_retirement.py
test/llm/test_system_model_autofill.py
test/llm/test_workbench_update_merge.py
test/llm/test_llm_system_config_consumers.py
test/llm/test_llm_share_fallback.py
test/llm/test_chat_title_default_model.py
test/knowledge_unification/test_kn_creation_settings.py
test/knowledge_unification/test_kn_creation.py
test/knowledge_unification/test_kn_creation_api.py
test/knowledge_unification/test_llm_default*.py
test/knowledge_unification/test_llm_inherit.py
test/knowledge_unification/test_model_default_slot_admission.py
test/knowledge_unification/test_workbench_reference_atomicity.py
test/knowledge_unification/test_kn_space_reference_lifecycle.py
test/knowledge/test_knowledge_space_create_quota.py
test/knowledge/test_qa_recall_repository.py
test/knowledge/test_qa_recall_authorization.py
test/workflow/test_legacy_trace_retirement.py
test/workflow/test_workflow_session_title.py
test/citation/test_message_citation_relations.py
test/citation/test_strip_unregistered_markers.py
test/dsh/test_billing_scope.py
```

前端在 `src/frontend/platform/` 使用 `pnpm exec vitest run <以下文件> --maxWorkers=1 --minWorkers=1`；SourceEntry 单独执行，其余组合执行：

```text
src/pages/ModelPage/manage/tabs/WorkbenchModel.test.tsx
src/pages/ModelPage/manage/tabs/WorkbenchModel.commit.test.tsx
src/pages/ModelPage/manage/tabs/knowledgeModelRetention.test.tsx
src/pages/ModelPage/manage/tabs/systemModelSaveSource.test.tsx
src/test/knowledgeModelValidation.test.ts
src/pages/ChatAppPage/components/ResouceModal.test.tsx
src/pages/ChatAppPage/components/ResouceModal.security.test.tsx
src/test/f118KnowledgeLibraryDialog.test.tsx
src/components/bs-comp/chatComponent/CitationDocumentPreview.test.tsx
src/components/bs-comp/chatComponent/SourceEntry.test.tsx
```

## 原有失败与限制

后端失败分为原有工作台可选语音投影 3 项、空间删除 6 项、本地 SQLite 配额环境 11 项、计费策略 2 项。均与独立原始基线逐节点对照；本次不修无关功能。完整失败节点如下：

```text
test/knowledge_unification/test_llm_default_consumers.py::test_native_workbench_http_projects_optional_slots_without_mutating_repair_settings[False]
test/knowledge_unification/test_llm_default_consumers.py::test_native_workbench_http_projects_optional_slots_without_mutating_repair_settings[True]
test/knowledge_unification/test_llm_default_consumers.py::test_native_runtime_voice_is_removed_independently_of_valid_chat[offline]
test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_space_delete_clear_keep_projection_order_atomic_refs_and_sync_original_ids[False]
test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_space_delete_clear_keep_projection_order_atomic_refs_and_sync_original_ids[True]
test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_space_projection_failure_keeps_business_refs_and_does_not_purge
test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_clear_does_not_require_deleted_model_execution_or_release_model_binding
test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_folder_delete_does_not_silently_unbind_retained_channel_configuration[False]
test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_folder_delete_does_not_silently_unbind_retained_channel_configuration[True]
test/knowledge/test_knowledge_space_create_quota.py::TestEffectiveQuota::test_role_quota_raises_the_ceiling
test/knowledge/test_knowledge_space_create_quota.py::TestEffectiveQuota::test_role_quota_lowers_the_ceiling
test/knowledge/test_knowledge_space_create_quota.py::TestEffectiveQuota::test_role_unlimited
test/knowledge/test_knowledge_space_create_quota.py::TestEffectiveQuota::test_missing_key_falls_back_to_default
test/knowledge/test_knowledge_space_create_quota.py::TestEffectiveQuota::test_multi_role_takes_max
test/knowledge/test_knowledge_space_create_quota.py::TestCreationGate::test_unlimited_quota_skips_counting
test/knowledge/test_knowledge_space_create_quota.py::TestCreationGate::test_allows_when_below_quota
test/knowledge/test_knowledge_space_create_quota.py::TestCreationGate::test_blocks_when_quota_reached
test/knowledge/test_knowledge_space_create_quota.py::TestCreationGate::test_raised_quota_lets_the_51st_through
test/knowledge/test_knowledge_space_create_quota.py::TestCreationGate::test_zero_quota_blocks_immediately
test/knowledge/test_knowledge_space_create_quota.py::TestCreationGate::test_counts_exclude_department_spaces
test/dsh/test_billing_scope.py::test_user_cannot_bill_a_model_outside_their_scope
test/dsh/test_billing_scope.py::test_admin_chosen_helper_model_is_billed_without_the_scope_check
```

前端原有失败：空间创建页面文字计数断言 1 项（找不到 `0/10`）；引用预览 2 项（当前 Node 测试环境的 `localStorage.getItem` 不可用）。不是新设置逻辑失败，未修改无关实现或测试环境。

真实 MySQL/DM8、Milvus/ES、OpenFGA、MinIO 和在线模型的联调，以及真实登录后的浏览器操作尚未执行。API 测试的认证/授权边界有替身，不宣称真实 JWT 或 OpenFGA 验收通过。见 [E2E 清单](./e2e-checklist.md)，QA 参考表仍为待执行。

## 合入最新发版线复核（2026-11-27）

- 目标分支 `feat/3.1.0` 最新远端父提交为 `5a3bb1ae1c`，包含角色权限功能；本次合并提交为 `3093aaf227`。两个提交和本功能提交均为合并结果的祖先，无冲突。
- 合并后核对本功能原 66 个改动路径，内容与功能分支一致；远端新增角色权限生产代码保持。
- 合并后本功能关键后端回归 **192 passed**；Platform 核心表单、历史按钮及弹窗回归 **28 passed**；类型检查与三语检查通过。
- 整包 lint 发现远端 `f048ModelEditor.test.tsx` 新增的 6 个中文测试租户名称违规；单独将测试值改为英文并同步断言，不修改权限业务逻辑或翻译。该文件 **19 passed**；整包 lint 随后通过，仅保留原有 1 条无用 eslint-disable 警告。
- `git diff --check` 通过。完整环境验收和部署状态仍按上文记录，不因合入而视为已执行。
