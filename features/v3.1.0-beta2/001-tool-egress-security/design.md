# 两入口固定公网安全设计

用户确认最终简化：仅 /tool/test 与 /tool/schema URL下载使用安全异步传输，固定公网，无配置、无私网例外。未部署。

## 入口与连接

- 保留两入口临时全局超管准入；纯file_content解析不变。
- TestOpenApiTools只供测试入口调用；正常OpenApiTools、ToolExecutor、BoundedOpenApiTools精确HEAD，不接管正常工具执行。
- 严格解析最终HTTP(S) URL；全部A/AAAA及IP字面量固定公网校验，任一禁止地址即拒绝。无策略参数、无私网放行代码。
- FrozenResolver固定已验证IP，保留Host/SNI与TLS证书校验；禁重定向、环境/客户端代理。
- identity-only；测试1MiB、Schema2MiB；总期限最多30秒、连接最多5秒；流式限额、异常脱敏。

## 删除范围

删除ToolEgressConf、Settings字段、入口策略注入、EgressPolicy及私网例外逻辑、部署YAML示例。Schema下载无需读取Settings；不增加环境变量或数据库配置。正常内部工具无需迁移。

## 架构与验证

遵循constitution C1/C4/C5/C6，独立传输包不反向依赖bisheng。无数据库或权限模型变更。覆盖普通用户拒绝、管理员不能豁免、私网字面量/解析结果无条件拒绝、DNS固定及TLS、代理/跳转、大小/期限和原工具执行契约。

验证结果见verification.md。未验证生产登录、网关、DNS与内网。正常执行同族风险及其他入口不在本补丁范围。DNS期限后底层解析可能继续但不建立HTTP连接，并发资源压力待部署验证。
