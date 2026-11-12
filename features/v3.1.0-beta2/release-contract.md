# Release Contract — v3.1.0-beta2

仅登记当前安全补丁，不推断本版本其他功能归属；全局架构约束沿用 docs/constitution.md。

## 领域归属

| 领域 | Owner Feature | 范围 |
| --- | --- | --- |
| 工具测试及 Schema 下载 SSRF 修复 | 001-tool-egress-security | 仅两个入口临时超管限制及安全异步出站；内容解析不变，不改变工具数据归属 |

## 跨 Feature 不变量

| ID | 不变量 | 来源 |
| --- | --- | --- |
| INV-1 | 仅 `/tool/test` 与 `/tool/schema` URL 下载必须执行实际连接安全策略；管理员不能豁免，保持 identity/max/time/no redirects 限制 | 001-tool-egress-security |
| INV-2 | 两入口固定仅允许公网，无配置或私网例外；正常 OpenApiTools、ToolExecutor、BoundedOpenApiTools 精确保持 HEAD 执行契约，正常内部工具无需迁移 | 001-tool-egress-security |

## 依赖、风险与验证

复用现有登录、全局超管身份及工具权限体系，不新增领域对象、数据库字段或权限体系。临时准入的恢复需独立评估。

正常执行保留已知同族 SSRF/出站风险，非本补丁覆盖；不提供同步安全传输或全局工具出站保护。历史 195 passed 属于已撤销的扩大范围阶段；当前最终回归待主实施者补实际结果，不作为已通过发版门禁。

## 变更历史

| 日期 | 内容 |
| --- | --- |
| 2026-11-12 | 用户确认仅保护两个入口，撤销正常执行全局限制、同步传输及内部工具迁移要求；最终验证待补 |
