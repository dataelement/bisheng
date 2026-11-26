# 最终固定公网方案验证记录

## 结论

用户确认撤掉私网例外配置、接线和示例。当前两个入口固定公网，无配置或策略注入参数；正常工具执行保持HEAD。未提交、未合并、未部署。

## Python 3.11 验证

解释器：/Users/wenruli/code/project/bisheng/bisheng-kunlian-sso-planning/src/backend/.venv/bin/python（CPython3.11.14）；cwd当前树src/backend，只读复用环境，不改依赖锁。

RED：test_no_private_exception_configuration_exists 修复前1 failed（Settings仍有tool_egress）。移除后通过。策略测试新增禁止旧policy参数、无EgressPolicy/normalize_origin及私网字面量/私网DNS无条件拒绝；没有保留任何私网放行分支。

入口、固定公网策略、异步连接、脱敏测试：110 passed。与原执行契约及业务回归合并：**243 passed，7条既有第三方warning，4.81秒，exit0**。

```bash
/Users/wenruli/code/project/bisheng/bisheng-kunlian-sso-planning/src/backend/.venv/bin/python -m pytest test/tool/test_tool_ssrf_entry_guards.py test/tool/test_openapi_egress_wiring.py test/tool/test_egress_policy.py test/tool/test_safe_http_async.py test/tool/test_tool_egress_config.py test/tool/test_openapi_legacy_contract.py test/tool/test_tool_api_transport.py test/e2e/test_e2e_tool_api.py test/tool/test_tool_executor_permissions.py test/tool/test_parse_preset_extra.py test/tool/test_tool_api_schema.py test/tool/test_tool_api_nested_schema.py -q
```

测试数少于历史266，是因为删除私网例外配置/允许场景测试，改为固定拒绝；不是跳过失败测试。历史195/266不作为当前验收结果。

## 质量及不变性

Ruff通过，git diff --check及arch-guard exit0。定向git diff --exit-code HEAD确认以下文件完全无差异：Settings、部署config.yaml、正常OpenApiTools、ToolExecutor、BoundedOpenApiTools。核心恢复在上一阶段已测试先行验证，包括同步非200报错、异步正文、注入client、内网URL、proxy、95秒timeout和参数映射；本轮合并复跑再次通过。

## 实际行为与剩余边界

/tool/test与/tool/schema URL下载临时超管准入；超管仍只能请求安全公网。两个入口不能测试内网API或从内网URL导入，可提交文档内容解析；已保存内部工具正常执行无需迁移。两入口仍禁跳转/代理，identity-only、1MiB测试/2MiB下载、总30秒/连接5秒。

未执行真实登录、部署网关、生产DNS或业务网络验证；未运行全仓coverage/中间件集成。正常执行与其他入口的同族风险不在本补丁覆盖。DNS超时后的底层解析可能继续但不建立HTTP连接，并发资源压力待环境验证。
