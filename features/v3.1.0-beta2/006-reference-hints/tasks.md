# Tasks: 引用关系辅助提示

**关联规格**：[spec.md](./spec.md) · [design.md](./design.md)。版本：v3.1.0-beta2。

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | 用户确认，含其明确的 AC-14 |
| design.md | ✅ 已评审 | 用户“开发吧”确认修订设计并授权实施 |
| test-cases.md | ✅ 已生成 | QA 参考 20 条，八列表已检查，非执行结果 |
| tasks.md | ✅ 已拆解 | 已按 tasks 清单自审；不新增强一致机制或数据迁移 |
| 实现 | ✅ 已完成 | T001–T026 已实现及本地回归；环境 E2E 按用户安排后续执行，正式审查见 code-review.md |

## 执行说明

后端先写有意义的失败/权限/兼容回归再实现；测试文件路径以 src/backend/ 为根，后端实现路径以 src/backend/bisheng/ 为根，前端以 src/frontend/ 为根。按依赖顺序推进，不创建并行 agent。通知只在真正拥有业务提交的应用边界，不用全局ORM hook。涉及原有公共文件仅修改本特性的引用依赖部分。

## Tasks

- [x] **T001**: 主流程与任务新语义测试
  **文件**：`test/resource_reference/test_source_read.py, test/resource_reference/test_source_sync.py`
  **逻辑/验证**：故障注入验证缺索引读/实际权限、旧表替换、任务重试与租户。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-10, AC-11, AC-12
  **依赖**：无

- [x] **T002**: 读取运行时解除索引准入
  **文件**：`resource_reference/application/source_read.py, resource_reference/application/source_contracts.py`
  **逻辑/验证**：保留业务快照及实际目标校验，取消 source set/root/digest 依赖与索引 revision 结果。
  **覆盖 AC**: AC-07, AC-12
  **依赖**：T001

- [x] **T003**: 模型目标直接读取
  **文件**：`llm/domain/repositories/source_read_target_repository.py, llm/application/source_read_target_owner.py`
  **逻辑/验证**：移除 original 索引与 Run 证明，保留真实模型/服务和共享判断，同步异步一致。
  **覆盖 AC**: AC-07, AC-12
  **依赖**：T002

- [x] **T004**: 知识目标直接读取
  **文件**：`knowledge/domain/repositories/source_read_target_repository.py, knowledge/application/source_read_target_owner.py`
  **逻辑/验证**：从实体读取目标、空间及删除状态，保留实际租户规则。
  **覆盖 AC**: AC-07, AC-12
  **依赖**：T002

- [x] **T005**: 异步旧表刷新实现
  **文件**：`resource_reference/application/source_sync.py, resource_reference/domain/repositories/reference_sync_repository.py`
  **逻辑/验证**：六类来源根读取及旧表替换，应用原绑定特殊处理，无新表或迁移。
  **覆盖 AC**: AC-01, AC-08, AC-09, AC-11
  **依赖**：T001

- [x] **T006**: 任务注册与通知
  **文件**：`worker/resource_reference.py, worker/__init__.py`
  **逻辑/验证**：显式 tenant_id 参数及 headers 恢复 ContextVar；失败五次重试；通知位于提交后。
  **覆盖 AC**: AC-08, AC-09
  **依赖**：T005

- [x] **T007**: 助手读写及旧名称测试
  **文件**：`test/resource_reference/test_business_writes.py`
  **逻辑/验证**：旧名称不依赖集合标记，原值可编辑，实际模型未确定才拒绝调用。
  **覆盖 AC**: AC-07, AC-08, AC-13
  **依赖**：T001

- [x] **T008**: 助手读写解耦
  **文件**：`assistant/application/reference_source_owner.py, assistant/domain/repositories/reference_source_repository.py, api/services/assistant.py`
  **逻辑/验证**：按原配置值兼容旧名称，业务成功后通知根，不同步写引用。
  **覆盖 AC**: AC-07, AC-08, AC-13
  **依赖**：T007, T006

- [x] **T009**: 工作流保存与版本闭环
  **文件**：`api/services/flow.py, workflow/application/execution_admission.py`
  **逻辑/验证**：新增/保存/切换/删除版本按业务自身规则，提交后通知，保留实际版本权限。
  **覆盖 AC**: AC-07, AC-08, AC-13
  **依赖**：T006

- [x] **T010**: 默认模型与空间模型闭环
  **文件**：`llm/application/model_default.py, knowledge/application/model_reference.py`
  **逻辑/验证**：保留真实模型配置和重建状态，取消索引事务，最终提交后通知。
  **覆盖 AC**: AC-01, AC-07, AC-08
  **依赖**：T006

- [x] **T011**: 元数据、移动和租户测试
  **文件**：`test/resource_reference/test_metadata_tenant.py, test/resource_reference/test_deletion_hints.py`
  **逻辑/验证**：元数据直接读取；移动引用故障独立；孤儿账本不拦截创建。
  **覆盖 AC**: AC-02, AC-07, AC-10, AC-12
  **依赖**：T001

- [x] **T012**: 元数据与移动解耦
  **文件**：`knowledge/application/metadata_owner.py, knowledge/application/move_processing_owner.py`
  **逻辑/验证**：从实际配置读处理版本，移除移动事务中的引用维护。
  **覆盖 AC**: AC-02, AC-07, AC-12
  **依赖**：T011

- [x] **T013**: 安装及租户解耦
  **文件**：`tenant/application/installation.py, tenant/application/tenant_creation.py, tenant/domain/services/tenant_service.py`
  **逻辑/验证**：取消覆盖证书准入，不改其他初始化或租户约束。
  **覆盖 AC**: AC-10, AC-11
  **依赖**：T011

- [x] **T014**: 应用原绑定与局部调用测试
  **文件**：`test/resource_reference/test_app_bindings.py`
  **逻辑/验证**：新版本 JSON、旧绑定保留、同名替换及映射缺失只影响相关实际能力。
  **覆盖 AC**: AC-07, AC-11, AC-13, AC-14
  **依赖**：T001

- [x] **T015**: 应用业务绑定快照
  **文件**：`app_publish/application/reference_source_owner.py, app_publish/domain/services/version_service.py`
  **逻辑/验证**：新增版本正常 INSERT 保存原目标JSON；旧版本只读原ID，不回写或按名猜绑。
  **覆盖 AC**: AC-07, AC-08, AC-11, AC-13, AC-14
  **依赖**：T014, T006

- [x] **T016**: 应用实际调用与生命周期
  **文件**：`app_publish/domain/services/capability_bus_service.py, app_publish/application/reference_access.py, app_runtime/domain/services/app_state_service.py`
  **逻辑/验证**：独立能力读取，实际被请求能力才校验；删除应用提交后清理来源。
  **覆盖 AC**: AC-07, AC-12, AC-13, AC-14
  **依赖**：T015

- [x] **T017**: 频道及默认系统写入口
  **文件**：`channel/domain/services/channel_service.py, channel/application/reference_source_owner.py`
  **逻辑/验证**：现有频道来源及系统配置入口不漏通知，不为关闭开关造新语义。
  **覆盖 AC**: AC-01, AC-07, AC-08
  **依赖**：T006

- [x] **T018**: 删除提示及执行新语义测试
  **文件**：`test/resource_reference/test_deletion_hints.py`
  **逻辑/验证**：查询失败、引用变化、已知引用、旧计划恢复和权限拒绝。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-12, AC-13
  **依赖**：T001

- [x] **T019**: 知识引用普通查询
  **文件**：`knowledge/domain/services/knowledge_reference_service.py, resource_reference/domain/repositories/reference_hint_repository.py`
  **逻辑/验证**：直接索引读取及实际文件归属，独立Session和两秒预算，不要求全局账本。
  **覆盖 AC**: AC-01, AC-04, AC-06
  **依赖**：T018

- [x] **T020**: 知识删除确认与执行
  **文件**：`knowledge/application/knowledge_delete_precheck.py, knowledge/application/knowledge_deletion.py`
  **逻辑/验证**：提示与业务计划分离；保留权限及真实清理恢复；旧计划不比较引用。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-13
  **依赖**：T019

- [x] **T021**: 模型删除提示
  **文件**：`llm/domain/services/model_reference_service.py, llm/domain/repositories/model_delete_plan_repository.py`
  **逻辑/验证**：取消Coverage和引用冻结，旧计划可读，新impact不签提示。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06
  **依赖**：T018

- [x] **T022**: 模型删除执行
  **文件**：`llm/application/model_delete_plan.py, llm/application/model_deletion.py`
  **逻辑/验证**：引用不是资格，真实provider清理/幂等保持，移除引用状态比较。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-13
  **依赖**：T021

- [x] **T023**: 平台提示及交互测试
  **文件**：`platform/src/pages/KnowledgePage/components/KnowledgeDeletionDialog.test.tsx, platform/src/pages/ModelPage/manage/ModelRemovalDialog.test.tsx`
  **逻辑/验证**：业务可执行而引用失败时仍可确认；可见性及提示不误报空集。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06
  **依赖**：T018

- [x] **T024**: 平台知识删除提示
  **文件**：`platform/src/controllers/API/knowledgeDeletion.ts, platform/src/pages/KnowledgePage/components/KnowledgeDeletionDialog.tsx, platform/src/pages/KnowledgePage/hooks/useKnowledgeDeletion.ts`
  **逻辑/验证**：提示布尔独立，取消引用force/禁用，保留真实业务确认。
  **覆盖 AC**: AC-03, AC-04, AC-05
  **依赖**：T020, T023

- [x] **T025**: 平台模型删除提示及三语
  **文件**：`platform/src/pages/ModelPage/manage/ModelRemovalDialog.tsx, platform/src/pages/ModelPage/manage/useModelRemoval.ts, platform/public/locales/{zh-Hans,en-US,ja}/{knowledge,model}.json`
  **逻辑/验证**：移除引用检查完整性提交前提，提示只读旧记录；三语同步。
  **覆盖 AC**: AC-03, AC-04, AC-05
  **依赖**：T022, T023

- [x] **T026**: 回归适配与本地复核（环境 E2E 由用户后续执行）
  **文件**：`test/resource_reference/, features/v3.1.0-beta2/006-reference-hints/verification.md`
  **逻辑/验证**：适配并合并运行本地回归及前端测试；与同起点基线逐项比对，记录剩余既有失败及环境限制。正式合入前特性审查仍按 SDD 第 8 步执行。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14
  **依赖**：T008, T009, T010, T012, T013, T016, T017, T020, T022, T024, T025

## 实际偏差记录

实现与设计对齐记录见 design.md 实施补充。本地使用 SQLite/ASGI 和外部传输替身，不能替代 MySQL/DM8、真实 worker 与浏览器验收。用户已明确由其在更新开发环境后自行执行环境 E2E；本轮负责完成回归适配和本地复核，环境清单保留待用户验证。


## 2026-11-25 工作流运行前预检修复

- [x] 用户确认排查结论与修复方案；补充 AC-15 至 AC-18、设计 §4.12。
- [x] 后端只读预检、批量绑定检查、全节点错误定位，保留执行重校验。
- [x] 前端运行入口拦截、重复点击保护、快照变化检查与节点/字段标红。
- [x] 本地质量检查及真实 SQL 回归完成；见 docs/reviews/workflow-reference-preflight-166-20261125.md。
- [x] 166 API/页面核验、普通用户及匿名拒绝、部署和回退记录。
- [x] 七维度审查完成；合入并推送 beta2 随本修复收尾。
