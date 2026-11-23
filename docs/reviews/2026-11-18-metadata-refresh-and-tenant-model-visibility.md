# 元数据重复刷新修复与 116 模型可见性排查

## 范围与基线

- 基线：远端 `feat/3.1.0-beta1`，`312db1c7241b92b17dcab9d0b8e85dc08042a008`。
- 分支：`codex/3.1.0-beta1/metadata-refresh-scope-20261118`；使用本任务原有独立工作区，主工作区保留。
- 本轮修改前端缓存刷新和相关设计/测试；116 仅只读检查。无数据库迁移、权限变更、任务恢复或部署。

## 元数据请求放大

用户确认 2026-11-18 15:52:14 对空间 3124 的新增操作。数据库任务 `e004d9ac-1320-4fbf-87d7-cb137c261c0b` 新增字符串字段 `ddd`，状态 succeeded，total_count=0，accepted_at 与 finished_at 同秒；没有对文件执行批量更新。

旧前端三层刷新：公共 createJob 使当前空间全部查询失效；元数据 hook 再读 schema、调用父 onSaved 使整个知识 scope 失效；完成时再次读 schema、调用同一父回调。116 前端包 `platform/assets/js/detail-DdpDmXO4.js` 已确认包含这条逻辑。

15:52:14.86–15:52:24，同一客户端来源的日志有 62 次知识/权限请求，包括 7 次元数据任务列表、6 次空间权限、5 次下载 inspect、4 次 schema，另一个空间 3547 的目录也查询 5 次。窗口内含原有复制轮询和其他活动，不能将 62 次全部归因于单次保存。

本次修复：

1. 预检计划缓存保留 digest 和 kind，确认后按原预检类型选择刷新范围；不增加服务端协议字段。
2. 元数据确认只使该 scope/空间的 schema、元数据或未筛选任务列表失效；去掉 hook 二次 schema 读取与父级整页回调。
3. 任务完成仅重新读取 schema。元数据重试只使 schema、相关任务列表、原任务及其失败项失效。
4. 字段新增、重命名、删除仍复用原预检、确认、幂等、失败草稿和异步进度，原编辑权限及租户退役检查保留。

### 同类路径检查

- 复制任务：旧代码每个已完成/失败计数变化都会使整个 scope 失效；改为仅对 job_id、阶段、状态或任务集合变化响应，刷新受影响副本和空间/导航列表。保留三秒任务轮询，不再由数量进度刷新无关空间或模型候选。
- 下载权限 inspect：它被旧空间/整页失效带动，元数据确认现在不会使其失效；没有改变下载鉴权或改成长期授权缓存。
- 移动、复制创建/结束、删除和权限变更确实会影响空间成员、目录或列表；不将这些业务刷新一概关闭。本轮不扩展为所有页面的缓存重构。

### 耗时边界

该次创建接口 HTTP_ACCESS_METRIC 为 0.1318s，部门列表样本 1.2127s，下载 inspect 样本 0.7065s。该指标从部分鉴权中间件之后开始计时；不包含浏览器排队、网络、网关或该中间件的前置工作。因此不能把浏览器截图的 2–4 秒直接解释成 SQL 慢查询，也不能仅凭该指标断言所有延迟已解决。

## 116：t338 / wangxinlei3

只读核对结果：

| 项目 | 实际值 |
|---|---|
| 租户 | 69，t338，租户回归部门，Root 的直接子租户 |
| 用户 | 841，wangxinlei3，租户 69 成员 active / is_active=1 |
| 系统配置 | 租户 69 没有自有 linsight_llm；Root 有配置且 share_default_to_children=1，继承条件成立 |
| 模型 | 908 / 932 / 933 / 936 / 937，全部在线，归属 Root |
| 子租户可见范围 | 上述五个模型在 dsh_model_visibility 中均有 tenant_id=69、everyone=1、subjects=[] |
| 服务商共享 | 模型所属 Root 服务商 335 / 337 均没有 tenant:69 的 shared_with；OpenFGA Check 均为 false |

Root 模型 908 的可见范围确实限定部门 95，但它不是本次筛除原因。116 开启 DSH；UnifiedPolicyRepository.effective 严格读取当前租户的策略，租户 69 的五个模型已全员可见。随后 `_project_models` 调用 `get_dsh_model_snapshot`，其 `get_model_for_call` 要求 Root 服务商对当前租户存在有效共享；这里失败后被按 DshModelNotAllowedError 过滤。

### 为什么缺少共享

租户 69 的 DB create_time 为 2026-11-18 11:46:59。API 日志 `bisheng.2026-11-18_11-40-07_709477.log` 的同一 trace `591c1eb494214e45ad186aa9cc1f39d6`：

- 11:47:17.370947：数据库会话回滚，错误 `The operation impact has changed; review and confirm it again`。
- 11:47:17.374079：`[F029] llm_server fanout to child 69 failed: not all arguments converted during string formatting`。

挂载源码有自动下发服务商共享的流程，但失败被捕获，租户仍可创建成功。该流程内部的异常日志还用了标准 logging 不支持的 `{}` 占位符；`InterceptHandler.emit` 的 record.getMessage 会再次异常，遮盖原始共享错误并中止剩余服务商循环。因此现场状态是“配置及可见策略已准备、共享下发未完成”，不应绕过共享鉴权。

尚未确定原始 impact-changed 是哪一项内部事实校验触发；没有重新执行写流程来取得堆栈。建议后续修复这条受保护的挂载共享流程及其失败诊断，核实原操作/版本证据后通过原业务入口恢复缺失授权。不要通过临时 SQL、直接 OpenFGA tuple 写入或放宽 Root 模型调用校验修复。

## 验证与审查

- 定向 metadata/schema、文件字段、任务进度、复制刷新、scope、侧栏、详情及管理页组合回归：123 passed / 3 failed；同一选择在基线为 120 passed / 相同 3 failed，新增 3 个回归用例通过。失败均为既有 knowledgeSpaceManagementView 测试。
- 元数据面板新增断言：一次新增只产生初始 schema 读取和确认后一次读取，不再重复读取。
- 修改文件定向 ESLint 通过；全量 lint 被既有 SpaceUploadPreview.tsx:230 的 file.filePath effect 依赖问题阻断，基线复现。
- 全量 typecheck 被既有 SpaceFileUploadPanel.tsx:397–398 的 strategy 可能为空问题阻断；基线同样两处错误，无本次修改文件类型错误。
- 平台生产构建、check-i18n、逐修改文件 arch-guard、git diff --check 通过。
- 按 sdd-code-review 检查边界、权限、并发、泄漏、测试、风格、文档七个维度；本次差异无新增阻断项。没有变更 API、数据库、授权规则、UI 样式或文案。
- 未部署；未在 116 执行新增/重命名/删除字段、模型授权恢复或实际模型调用。部署后还需浏览器验收网络请求数量、任务失败重试及租户切换。
