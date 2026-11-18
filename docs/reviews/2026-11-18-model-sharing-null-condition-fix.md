# 模型共享 condition:null 兼容热修复

- 日期：2026-11-18
- 分支：`codex/3.1.0-beta1/model-sharing-null-condition-20261118`
- 基线：远端 `feat/3.1.0-beta1` 的 `ead9f11842c7fc30b94e532b77cd34d3807d29d0`
- 范围：修复共享关系读取，不改变 API、数据库结构、授权语义或恢复围栏。主工作区的未提交改动保留。

## 根因与修复

116 的 OpenFGA `/read` 返回合法无条件关系时，tuple key 包含 `user/relation/object/condition`，其中 condition 为 null。真实 FGAClient 保留这个字段；共享 owner 原来仅接受三个字段，因此开启、关闭或补共享时均可能返回 `25008: Model sharing projection: invalid existing sharing tuple`。

`ModelSharingProjectionApplication.aread` 现在仅接受原三字段，或额外带 `condition: None` 的四字段。实际条件对象、空对象、其他非空 condition 及未知字段仍拒绝。资源、关系、规范正整数租户 ID、重复主体和授权 Store/Model pin 保护不变。不在通用客户端删除字段，避免其他调用方误将有条件授权当成无条件授权。

同类审计：`f118_permission_publish.ascan` 已按相同规则接受空 condition，无需改动；`FGAProjectionAdapter.read_present` 按目标字段读取，不存在精确字段集误判；`f048_runtime_verification._target_tuples` 读取的是内部冻结 TARGET_TUPLE JSON，不是 OpenFGA 原始响应，继续严格执行原三字段合同。

## 验证

- 新增真实 FGAClient + httpx MockTransport 回归：原实现 **2 failed / 14 passed**，复现空 condition 误拒及重复检测未到达的问题。
- 修复后针对性回归 **45 passed**：包括上述 16 项，以及共享开启/关闭/重复保存、超过单次写入上限的分页投影、持久 SQL 台账、模型删除围栏与恢复。
- 已有共享/删除测试的传输 fixture 改用 `condition: None`，覆盖生产响应形状；新增关闭读取失败后恢复用例，验证 PREPARING 保留、无提前撤权、相反开启命令被拒、同一关闭命令沿原计划完成。
- Ruff format/check、逐文件架构守卫与 `git diff --check` 通过。未改前端，无新增依赖。
- 守卫使用仓库相对路径执行。另核对绝对路径时，RULE-9 会因仓库目录名 `bisheng` 误把 `test/permission` 的真实客户端测试当成业务模块；该测试合法地直接测试基础设施，与已有 `test_fga_client.py` 同类。本轮没有修改守卫，也没有改用动态导入规避检测，生产权限 owner 的分层检查通过。
- 本地 SQL 回归使用隔离 SQLite，HTTP 使用隔离传输，不等同于 116 或 DM8 真实端到端验收。现存第三方和 SQLModel 弃用警告不影响测试结果。

测试命令（`src/backend`，使用项目 Python 3.11 虚拟环境）：

```sh
python -m pytest test/permission/test_model_sharing_tuple_read.py test/knowledge_unification/test_model_sharing_projection.py test/knowledge_unification/test_model_provider_sharing_writers.py test/knowledge_unification/test_model_provider_operation_repository.py test/knowledge_unification/test_model_deletion_application.py test/knowledge_unification/test_model_deletion_business.py -q
```

## 代码审查

按 `sdd-code-review` 清单自审本热修复，不代表独立人员审查或 CI 结果。

| 维度 | High | Medium | Low | 结论 |
|---|---:|---:|---:|---|
| 边界条件 | 0 | 0 | 0 | PASS：缺省/null、非空 condition、异常字段、分页和重复主体 |
| 权限与认证 | 0 | 0 | 0 | PASS：保留严格关系/资源/租户及 pin 校验，不增加授权 |
| 并发安全 | 0 | 0 | 0 | PASS：沿用持久计划、原命令摘要及同计划恢复，冲突命令继续拒绝 |
| 信息泄漏 | 0 | 0 | 0 | PASS：没有新增错误内容、日志或凭据 |
| 测试覆盖 | 0 | 0 | 0 | PASS：真实客户端读取及原生业务恢复回归 |
| 代码风格 | 0 | 0 | 0 | PASS：修改位于权限 owner；Ruff 和架构守卫通过 |
| 文档同步 | 0 | 0 | 0 | PASS：设计补充传输兼容决策、已知坑和重审条件 |

结论：PASS。按 Hotfix track 交付，不新增 spec/API/数据库合同。

## 116 后续验收

本轮不部署、不补授权、不删除或修改现场计划。

1. 部署后确认实际运行的 `aread` 包含空 condition 兼容逻辑。
2. 提供商 358 当前关闭计划 `dbacd76a-c5c2-494e-9bb7-41d0b49a2f77` 为本次只读排查时的 PREPARING 快照。执行前重新核对状态、原操作者和关闭意图；如继续关闭，由原操作者再次提交相同关闭操作，复用原计划，勿切换成开启来绕过围栏。关闭会撤销现有共享，须符合实际操作意图。
3. 确认同一计划完成、关闭结果正确且其他提供商授权不受影响；需要开启或补齐共享时，须先解决冲突中的原关闭操作，再按明确意图执行。
4. 提供商 12 的旧 PREPARING 时间精度问题及租户 69 缺失授权属于先前记录的独立恢复事项；本兼容修复不自动处理。
