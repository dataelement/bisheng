# 116 管理视图切换两类错误排查

排查日期：2026-11-13（Asia/Taipei）。环境：`http://192.168.106.116:3001`。账号：`zgqtest`，服务端身份为用户 191、主属 Root（租户 1）、全局超级管理员。

**结论：两张截图对应的错误均已通过真实接口稳定复现，入口都是 `GET /api/v1/workstation/config`。固定租户后重复请求仍然失败，不需要连续快速切换。模型列表能够正常加载，因此弹窗出现在模型页不代表模型列表接口失败。**

本轮只读核对业务配置和接口；为复现正常切换过管理视图，结束已恢复原来的“敏感审查”和 `/label` 页面。没有修改业务代码、角色绑定、配额、模型配置或共享关系，没有重启、部署或执行数据库清理。

## 1. 实测结果

以下重复请求均在管理视图稳定后发起；HTTP 状态均为 200，表格列出的是响应体业务状态码。

| 管理目标 | 工作台聚合配置 | 重复结果 | 对照 |
| --- | --- | --- | --- |
| 测试应用审批（租户 60） | `10996`，`reason=reference_target_invalid` | 连续 3 次相同错误 | 用户信息成功；模型列表成功，11 个提供方 |
| 敏感审查（租户 65） | `24006`，当前角色策略无法核实 | 两组各连续 3 次相同错误 | 用户信息成功；模型列表成功，18 个提供方 |
| Root（租户 1） | `200` | 单次对照及随后连续 3 次成功 | 用户信息成功 |

可供服务器日志定位的请求追踪标识：

| 请求 | 管理目标 | 业务结果 | `X-Trace-ID` |
| --- | --- | --- | --- |
| `/api/v1/workstation/config` | 60 | `10996 / reference_target_invalid` | `8ec9b3bc643146608b959480a58fef64` |
| `/api/v1/workstation/config/daily` | 60 | `10996 / reference_target_invalid` | `68176e6d1d4b447fb987a085b42bb93b` |
| `/api/v1/llm/workbench/settings` | 60 | `200`，原始配置可读 | `4507fd8682d34d60aa054e80c9279ae9` |
| `/api/v1/llm/workbench` | 60 | `24006` | `9959098c303e4a4090684ca251e70af8` |
| `/api/v1/workstation/config` | 65 | `24006` | `9d77ad9098154dbca38ba699c42a6809` |
| `/api/v1/workstation/config` | 1 | `200` | `a51ab823324848e4a553af2a998edf60` |

## 2. 为什么切换后在模型页弹出工作台错误

`src/frontend/platform/src/contexts/locationContext.tsx:120` 在全局配置加载后，无论当前业务页面是什么，都会调用完整的工作台聚合配置接口。当前使用其中的 `menuShow` 和 `assistantIcon.image` 设置界面。

`src/frontend/platform/src/components/HeaderTenantScope.tsx:67` 切换管理视图后清除查询缓存并重载页面，于是再次触发上述全局加载。错误先经过 `src/frontend/platform/src/controllers/request.ts` 的全局错误提示，再进入调用方的异常处理。

因此，在模型页、标注页等管理页面也会遇到工作台模型或个人策略的错误。此次样本说明错误与目标租户有关；尚未观察到需要用切换竞态解释的证据，也没有把旧请求丢弃等其他时序问题认定为不存在。

## 3. 角色策略错误：管理目标被当成个人策略所属租户

代码链路：

```text
AdminScopeMiddleware：管理目标固定为租户 65，账号身份仍属租户 1
  → workstation/config：authorized_workbench_models(user_id=191)
  → dsh.runtime.read_policy(191)
  → UnifiedPolicyRepository.effective(191)
  → DshSubjectPolicyRepository._department_ancestor_ids
  → policy_department_ids_sync(191, expected_home=65)
  → 实际主属租户 1 != 65，抛出 24006
```

对应代码：

- `src/backend/bisheng/workstation/api/endpoints/config.py:23`：聚合配置加载用户个人模型目录。
- `src/backend/bisheng/dsh/domain/services/model_catalog.py:16`：读取当前用户策略。
- `src/backend/bisheng/dsh/domain/repositories/unified_policy.py:180`：在当前租户上下文中计算部门、角色和个人配额。
- `src/backend/bisheng/dsh/domain/repositories/subject_policy.py:252`：将当前有效租户作为期望主属租户传入。
- `src/backend/bisheng/user/application/policy_bindings.py:70`：主属租户不一致即拒绝。
- 同仓储的 `_role_ids` 也有相同的期望主属租户校验，因此只绕过部门检查不能修复整个问题。

这是调用边界遗漏：**查看某个子租户的管理数据，不代表当前管理员成为该租户的普通成员，更不能据此计算其个人角色和配额。** 现有一致性校验拒绝混用身份是合理的，错误在于聚合入口把个人策略计算带入了管理目标上下文。

本地 `git blame` 显示，部门及角色读取接入这些主属租户校验的代码来自上一轮租户修复提交 `11da79e8bfb`；既有工作台聚合接口早已消费个人模型策略。上一轮修复遗漏了这条管理视图调用路径。不能以删除校验、全局改写登录用户的租户或放开租户过滤来解决。

补充对照：在租户 60 下，`/llm/workbench/settings` 原始配置读取成功，但 `/llm/workbench` 的用户模型投影返回 `24006`。说明角色策略错位并不限于租户 65；在聚合接口中，它可能被更早发生的引用错误遮住。

## 4. 资源引用错误：租户 60 的本地工作台配置存在不可用的 Root 引用

`/api/v1/llm/workbench/settings` 实测返回 `inherited_from_root=false`，即租户 60 有自己的工作台模型配置。其保存内容包括：

| 配置位置 | 保存的模型标识 | Root 实测存在 | 租户 60 模型列表可见 |
| --- | --- | --- | --- |
| 可选对话模型 | 908，MiniMax-M2.5 | 是，提供方 335 | 否 |
| 语音识别模型 | 924，16k_zh_en | 是，提供方 256 | 否 |
| 标题生成模型 | 935，deepseek-v4.1-flash | 是，提供方 12 | 否 |
| 图片识别模型 | 849，paddleocr-vl-1.5 | 是，提供方 279 | 否 |
| 对话默认模型 | 932 | 是，提供方 337 | 是 |
| 向量模型 | 934 | 是，提供方 337 | 是 |
| 语音合成模型 | 1141 | 属于租户 60 | 是，当前下线 |

上述四个不可见模型均在 Root 列表实际存在，不能笼统解释为“模型都被删除了”。模型 1141 下线也不能单凭下线状态被认定为本次引用校验失败的原因。

代码链路：

```text
workstation/config
  → WorkStationService.get_daily_chat_config(for_picker=True)
  → LLMService.get_workbench_llm_for_picker
  → get_workbench_llm / ModelDefaultReadRuntime.arequire_default
  → 对 linsight_llm 整个配置执行引用有效性校验
  → 任一目标 is_valid=false
  → 10996 / reference_target_invalid
```

`src/backend/bisheng/llm/application/source_read_target_owner.py:58` 要求现有跨租户引用满足模型共享或默认继承等资格；不能因为管理员是超级管理员就把子租户的实际使用资格放开。`src/backend/bisheng/resource_reference/application/source_read.py:56` 对任一无效引用拒绝执行整个配置。

实测配置、本地代码和子租户可见列表共同指向：租户 60 自有配置仍保留了当前不可用的 Root 模型引用，严格读取先于个人策略计算失败。租户 65 则继承 Root 配置（`inherited_from_root=true`），能够通过该阶段，随后暴露角色策略错位。

**证据限制：** 当前公开响应只给出聚合原因 `reference_target_invalid`，没有逐引用状态。尚未取得服务器数据库和后台日志，因此未直接读取这几个引用的台账状态、具体共享授权记录及变更历史，不能据此断言是哪次操作或迁移造成了原始配置失配。上表是实际配置与可见性的对照，不冒充逐引用台账检查结果。

## 5. 最小修复建议（本轮未实施）

1. **解除管理端全局启动对工作台运行时聚合接口的依赖。** 全局界面仅需菜单显隐和图标等元数据，不应因为完整工作台模型、工具或个人配额检查失败而在所有管理页面弹错。优先复用已有配置读取能力，提供最小的界面元数据投影；不新增业务表。
2. **明确个人策略与管理视图的上下文。** 普通角色、个人菜单及个人配额按服务端核实的主属租户计算；目标租户的工作台配置及合法继承仍按管理目标读取。进一步核对既有规格后，发现 `features/v2.5.1/019-admin-tenant-scope/spec.md:340` 还明确允许全局平台管理员的前台工作台视图跟随管理选择。因此不能把全部工作台配置或模型目录强制改回主属租户；需区分管理目标的展示/预览与真正的个人策略消费，并明确超管跨租户预览时的模型资格处理。不能只把 `expected_home` 改成 1，却仍在租户 65 查询该账号的个人配额规则。本报告初稿将用户工作台配置一概表述为主属租户，已据现有规格修正。
3. **单独修复租户 60 的无效配置。** 经业务确认后，在正常配置入口重新选择该租户可用的模型；如果确实需要使用 Root 模型，通过正常共享授权入口处理。保留原配置以便核对，不自动删除引用、不自动扩大共享。
4. **保留真正执行时的严格拒绝。** 模型调用仍需验证所有相关引用及权限。管理配置展示应能呈现待修复配置；不能通过关闭引用校验或吞掉全部角色错误让弹窗消失。

重点回归：Root 管理员在 Root、租户 60、租户 65 间切换；主属身份保持不变；管理端模型/标注页只加载所需界面配置；工作台个人策略只使用主属租户；无效配置可读可修且执行仍拒绝；真正角色策略异常仍返回错误；子租户普通用户、子租户管理员及桌面端各自的模型和配额规则不被扩大。

## 6. 取证边界

- 已完成：真实账号、真实接口复现；三个管理目标对照；原始模型配置与模型目录交叉检查；本地调用链及提交归属核对。
- 未完成：服务器 SSH 认证未通过，未读取容器代码、数据库引用台账或后台调用栈，未核验当前部署镜像的实际提交。因此没有将本地提交号写成现场部署版本。
- 本地排查期间主分支由其他任务推进；上述相关生产文件在初始 `9041f3c263` 至核对时 `3ce7e7ef3de81a06f57520a7ab74d6b9e253d8fc` 间无差异。既有未提交文件未处理。
- 临时脱敏记录：`/tmp/tenant-switch-probe-results-20261113.jsonl`，包含后半轮 Root/租户 65 对照及模型目录。租户 60 的三次错误和追踪标识保留在本次排查工具输出及本报告中。记录不含密码、登录令牌或模型密钥。
