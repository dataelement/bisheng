# E2E 覆盖报告

执行仓库 e2e-test 工作流，复用现有原生登录SQL/API链路测试和真实MCP SDK测试；本轮未新增一个依赖未提供部署账号的通用E2E基础框架。

| AC | 本地证据 | 实机状态 |
| --- | --- | --- |
| AC-01 | 安装器、真实YAML模型与Helm渲染 | 待实际启动 |
| AC-02、AC-03 | 默认值进入真实egress策略，wheel/npm/私有源拒绝回归，既有构建/出口测试 | 待真实下载与应用安装 |
| AC-04 | 无地址API授权/撤销，真实SQLite+PKCE/密码学换票与续期，两种地址模式；真实SDK initialize/tools/list/call/resources/list/read | 待真实Desktop/完整中间件 |
| AC-05、AC-06 | 固定origin回归与配置兼容/优先级/空块测试，Helm兼容覆盖 | 待部署确认 |
| AC-07、AC-09 | 错误Origin、重复Host、DNS代理peer、原生认证/Chat/工具权限回归，并发请求独立SDK策略 | 待真实代理、普通用户全链路 |
| AC-08 | 已有.env与凭据保持、开关组合、升级密钥保留 | 待真实升级 |
| AC-10 | README、QA参考、验证记录与本报告 | 已明确发行与部署边界 |

后端182 passed、2 skipped、5 deselected；部署47 passed、安装器18项；runtime100 passed、8 skipped。基线失败和缺少环境的细项见verification.md。

## 整体状态：PARTIAL

本地API/协议和配置验证已完成；没有真实部署环境，不能声称完整E2E验收通过。手动清单见e2e-checklist.md。
