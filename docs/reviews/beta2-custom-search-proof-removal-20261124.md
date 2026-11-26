# beta2 自定义搜索 proof 移除审查

日期：2026-11-24。范围：用户明确要求在 `feat/3.1.0-beta2` 移除操作证明；基线 `3168b8724b`。按 sdd-code-review 七维度检查本次差异，不重新宣称 F017 全特性验收通过。

## 结论：PASS

| 维度 | 结论 | 检查证据 |
| --- | --- | --- |
| 边界条件 | PASS | custom 继续限制字段、操作结构、请求参数、认证声明和映射；仅允许额外的旧 proof 字段并丢弃，未知其他字段仍拒绝。 |
| 权限与认证 | PASS | 管理端全局超管鉴权、类别租户归属、ToolExecutor 权限入口保留；目标租户合法配置可用，其他租户访问拒绝。搜索凭据仍单独加密并绑定租户和类别。 |
| 并发安全 | PASS | 配置 revision、事务与凭据保留/替换/清除路径保留；兼容转换构造新字典，不改 ORM 原值。 |
| 信息泄漏 | PASS | 不再返回 proof；API Key 不写入配置或通用 DTO；旧 proof 不解密、不输出日志，不从 Root 查找凭据。 |
| 测试覆盖 | PASS | 后端 55 passed + 9 subtests；前端 16 passed。含实际路由持久化链路、回环 HTTP 运行链路、旧配置兼容、参数错误、认证约束、非管理员及跨租户拒绝。 |
| 代码风格 | PASS | 删除 OperationCipher/issue_proof/verify_operation 及所有搜索调用方；无残留 SearchProof 类型或 proofRequired UI 提示。ruff、全量 lint/typecheck、i18n 和差异检查通过。 |
| 文档同步 | PASS | design §3.4 和 API/加密说明、任务替代、运维兼容及回归清单同步。 |

## 交付边界

不迁移数据库，不自动继承 Root 搜索凭据；未配置的子租户需填写获授权的凭据。新版前端、API、Worker 应一并更新，旧前端仍有 proof 必填检查。Schema 原文回显不属于本次修改。没有部署生产或运行真实供应商/PPT/MySQL/DM8 验收。

本地验证命令和结果见 [F017 验证记录](../../features/v3.1.0-beta1/017-custom-web-search/verification-local.md)，部署后手动验证见 [回归清单](../../features/v3.1.0-beta1/017-custom-web-search/e2e-checklist.md)。
