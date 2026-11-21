# F025 独立代码审查（修复后复审）

**最终判定：PASS。审查范围内无未关闭的High/Medium。**

**Feature**：子租户系统模型完整使用。
**审查基线**：`c36ba672be0ff2f79d0e7358954e77973d2495f2`。
**最终复审时间**：2026-11-18 19:08 Asia/Taipei。
**对象**：shared worktree最新未提交源码及新增测试，按`.claude/skills/sdd-code-review/SKILL.md`七维度复查。

范围为A的槽位core/verifier、真实授权及消费者；B的共享意图/冻结receipt/原命令恢复与接收可见初始化；Root的管理诊断/继承影响/批量接线/来源刷新/scope。C作者不在本报告中自评C实现。未重跑全套，以下定向测试由审查者亲自执行；唯一写入本报告，没有修改实现或测试文件。

## 七维度最终结果

| 维度 | 未关闭High | 未关闭Medium | 结论与依据 |
|---|---:|---:|---|
| 边界条件 | 0 | 0 | PASS：失效引用有显式修复入口；保存/运行统一slot类型与上线检查；空可选槽位不阻断其它能力 |
| 权限与认证 | 0 | 0 | PASS：继承不授权；真实执行租户核验共享；普通DTO移除失效语音引用；管理读前后核对scope与actor |
| 并发安全 | 0 | 0 | PASS：provider锁/intent版本/冻结receipt/原actor与command围栏；接收写入使用同一租户策略锁并保留本地限制 |
| 信息泄漏 | 0 | 0 | PASS：只诊断配置内引用，foreign child不返回名称，Root影响查询不向child开放，不返回凭据 |
| 测试覆盖 | 0 | 0 | PASS：独立执行后端62项、前端31项全通过，覆盖初审发现和修复的关键边界 |
| 代码风格 | 0 | 0 | PASS：未发现新增跨层越权写/业务直连OpenFGA；复审涉及文件diff whitespace检查通过，完整lint由总任务收尾 |
| 文档同步 | 0 | 0 | PASS（本轮范围）：spec/design核心合同与最终实现一致；总任务正在补齐最终交付文档，依Root指令不将进行中的验证稿计作功能缺陷 |

初审曾判NEEDS_FIX。下列2项High与5项Medium均已修复并有静态回读和定向运行证据；本次PASS不等于生产部署、DM8或真实用户验收通过。

## 初审问题的关闭证据

### H-01：继承失效模型无本地修复入口 — 已关闭

原工作台完整保留继承的`form.models`，可用表格却不显示未共享/删除项，管理员不能移除它们，保存继续携带这些ID并被拒绝。隐藏`image_read_model`也被原样提交却无编辑入口。

当前`tabs/WorkbenchModel.tsx`新增`unavailableConfiguredModels`及逐项显式删除按钮，原引用不会静默丢失；“其他设置”新增图像读取模型选择器，可清除或替换。实跑`WorkbenchModel.test.tsx`9项，其中明确覆盖保留直到主动移除、失效图像引用清除、替换为合法LLM。

### H-02：Root provider详情漏实例化状态服务 — 已关闭

原`LLMService.get_one_llm`调用实例方法`ModelSharingStatusService.aget(...)`却缺self，Root详情/创建后返回失败。当前使用`ModelSharingStatusService().aget(...)`。

实跑`test_model_actual_sharing_runtime.py`，包含真正经过`get_one_llm`业务接线的2个参数用例：显式off但尚有实际接收者，以及显式on但当前无接收者；验证实例调用及intent展示优先级。

### M-01：保存缺少slot类型/上线检查 — 已关闭

当前`ModelDefaultApplication._asave`在原目标绑定准备和锁定之后，用`ModelDefaultRepository.aread_slot_models`读取状态，并复用`default_reference_extractor.model_default_models_are_callable`检查每个引用的类型和上线，之后重新授权再保存。源中原本就有的缺失引用继续遵守F118精确原来源修复规则；新引入缺失目标仍由绑定receipt拒绝。

实跑真实ASGI/原actor/SQL测试：

`test_llm_defaults.py::test_native_evaluation_post_checks_locked_type_and_online_before_writing`：wrong-type、offline、valid共3项。拒绝时确认默认行和引用均未写入、审计未成功，合法LLM正常提交。

### M-02：运行DTO仍暴露失效语音ID — 已关闭

当前`project_workbench_runtime_capabilities(config, *, login_user=...)`对工作台模型对象分别进行独立slot准入；已知目标失效仅移除对应对象，权限/来源故障真实传播。原默认选择也按来源slot校验；调用方已经作出的合法个人候选回退保留其owner决定。Router传入原login_user，管理settings仍返回原始修复配置。

实跑：

- `test_llm_default_consumers.py::test_native_workbench_http_projects_optional_slots_without_mutating_repair_settings`共2项：普通HTTP响应移除错误类型/foreign child对象，保留合法图像/标题/聊天；坏来源digest继续拒绝；原始修复配置未写回。
- `test_llm_default_consumers.py::test_native_runtime_voice_is_removed_independently_of_valid_chat`共2项：未共享ASR、下线ASR分别关闭，合法文本模型和日常默认仍可返回，原ASR ID保留在管理数据。

### M-03：Root继承影响缓存未随保存失效 — 已关闭

知识、助手、评测、工作流、工作台的成功保存均同时invalidate`system-model-settings`与`system-model-settings-impact`。未点击过的impact查询继续disabled，保持按需读取。

实跑`tabs/systemModelSaveSource.test.tsx`和`tabs/WorkbenchModel.commit.test.tsx`，断言成功后两个key都失效；失败保存不失效、不伪造本地来源。

### M-04：成功保存后来源徽标/诊断不刷新 — 已关闭

`useSystemConfigEnvelope`提供稳定reload及mounted/generation迟到响应保护。四个简单tab成功后重读保存来源；Workbench重读自身envelope并失效诊断。知识提示词局部保存采用`reload({updateConfig:false})`，保留同栏其它未保存草稿。恢复继承只重挂当前栏目。

实跑来源保存、迟到响应、Workbench已提交但随后刷新失败等用例：成功才转换来源；失败保留草稿和继承徽标；一栏保存不会清掉另一栏草稿；提示词保存不丢同栏模型修复草稿。

### M-05：单租户无ambient context回归 — 已关闭

实际共享helper和`get_model_for_call`统一使用`_resolve_tenant_id`，沿原SQL合同：单租户无ambient context回落Root，多租户无执行上下文拒绝。实跑sync/async两种单租户兼容及两种无context拒绝用例。

## 实际执行的独立定向回归

后端使用主仓库`src/backend/.venv/bin/pytest`，`config`指向已有主仓库配置文件，业务数据库/权限均由隔离测试依赖提供。

```sh
pytest test/llm/test_model_actual_sharing_runtime.py \
  test/knowledge_unification/test_model_sharing_lifecycle.py \
  test/llm/test_system_model_settings.py -q -W ignore --tb=short
# 34 passed in 0.89s

pytest test/knowledge_unification/test_model_default_slot_admission.py \
  -q -W ignore --tb=short
# 21 passed in 0.53s

pytest test/knowledge_unification/test_llm_defaults.py::test_native_evaluation_post_checks_locked_type_and_online_before_writing \
  test/knowledge_unification/test_llm_default_consumers.py::test_native_workbench_http_projects_optional_slots_without_mutating_repair_settings \
  test/knowledge_unification/test_llm_default_consumers.py::test_native_runtime_voice_is_removed_independently_of_valid_chat \
  -q -W ignore --tb=short
# 7 passed in 0.33s
```

后端独立定向合计：**62 passed**。包括真实SQLite原生事务、ASGI请求、完整来源digest、slot类型/上线、Root/child共享撤销、冻结receipt重试、旧无receipt不补历史授权、原相反命令保护、本地限制保留、Root影响接收者读取。

前端在platform目录执行`pnpm exec vitest run`，文件为：

- `useSystemConfigEnvelope.test.tsx`
- `SystemModelDiagnostics.test.tsx`
- `tabs/systemModelSaveSource.test.tsx`
- `tabs/WorkbenchModel.commit.test.tsx`
- `tabs/WorkbenchModel.test.tsx`
- `SystemModelConfig.test.tsx`

第一组4文件20 passed，第二组2文件11 passed；合计**31 passed**。存在React测试环境的既有warning输出，没有失败。未将不存在的测试文件当作已执行覆盖。

复审涉及的默认保存/运行、Router、对应新增测试及tab文件`git diff --check`无输出。

## 关键安全和恢复边界

- **A来源完整性**：slot选择仅MODEL_DEFAULT来源；完整snapshot references与索引digest/extractor/revision/effective仍核验，选定事实只覆盖选定slot。没有改写数据库引用集合或旧digest。标量/投影不返回未准入模型引用。
- **A真实授权与消费者**：执行租户不再借Root来源owner获权；selected targets核对真实Root提供商共享，继承server IDs捷径删除。检查了知识抽取/摘要/ASR/embedding、助手推理/auto_llm、工作流助手、Work任务、标题、图像及Open API消费者；助手节点保持助手栏目。
- **B冻结与恢复**：delta接收者和模型集合在RESERVED前持久化；接收初始化、intent和COMPLETED同事务。失败重试用原receipt，不因新成员重算旧集合。旧无receipt计划不补历史可见规则。
- **B并发与限制**：接收初始化锁Tenant行，与既有visibility管理员写使用同一租户锁；已有规则跳过，audit同事务。新模型接收快照有intent version/plan pin，集合变化要求重试。
- **B历史与原命令**：无intent不推定on；挂载/重新启用只消费显式on；活动相反命令受原actor/command digest围栏保护。没有清账本、重签旧摘要或GET授权。
- **Root诊断与影响**：前后`ModelDefaultApplication._authorize`及`current_model_default_tenant(expected)`核对scope。foreign child只返回原ID/status不回名称；未共享Root名称仅修复引用可见，不变成执行候选。Root影响查询按需执行，child的include_impact不会进入跨租户分支；原actor/data_scope授权继续生效。
- **Root页面scope**：按identity/tenant/managementTenant重挂载，query key含scope；vision按100分块，单行不自行GET。价格编辑入口依据服务端只读事实。请求层管理scope守卫和scope改变刷新仍有效。

## 限制与最终交付边界

本报告仅对上述源码范围与独立定向回归作PASS判定。完整lint/typecheck/build、最终SSOT文档和总E2E结果由总任务汇总；并非本报告已经运行。已在原始基线复现的DSH旧测试失败不记作本功能残留缺陷，证据见validation-C.md。真实116、DM8、多进程锁调度及真实普通用户调用仍需现场验收；本次没有部署或真实数据变更。

## 最后增量轻量复核：AC06与新表C3登记

2026-11-18 19:15 Asia/Taipei，最终判定保持**PASS，无新增High/Medium**。本段为轻量源码/测试及已有日志复核，没有再跑前述全套或定向组。

`agent_factory._resolve_model`在当前用户`project_workbench_config`投影后构造允许ID集合，并在调用`read_vision`/模型工厂前拒绝不在其中的显式模型ID；显式选择保持原ID，不替换成其它候选。日常Chat的`initialize_chat`和`_agent_initialize_chat`原有入口也先调用`user_workbench_models(user_id)`，找不到指定模型则在创建会话或模型前拒绝。新增`test/llm/test_user_model_visibility_execution.py`覆盖普通非DSH用户的Work和两个Chat入口，断言hidden ID遭拒及模型/会话工厂未调用。已读取`/tmp/tenant-model-a-visibility-tests.log`结尾，Owner最小组结果为**30 passed**；此增量日志不是本审查者再次运行的结果，不计入前述独立62项。

`core/database/tenant_filter.py`显式登记`bisheng.llm.domain.models.model_sharing_intent`；两个模型`ModelSharingIntent`、`ModelSharingInitialization`的`tenant_id`均`default=None`且数据库列nullable=False，由原自动填充事件写入当前租户。Root专属repository仍在校验原生Root事务后显式指定Root owner，未以模型默认值绕过隔离。`test/database/test_model_registry.py::test_sharing_intent_tables_are_registered_and_isolated_in_a_cold_process`用冷子进程实际注册事件，检查模型发现、Root/Child INSERT自动填充、SELECT互相隔离和显式bypass读取；测试源码覆盖该登记/默认值边界。Root另报告14项及集中23项通过，本次仅静态核对新增测试的实际断言，不将Owner结果表述为独立重跑。
