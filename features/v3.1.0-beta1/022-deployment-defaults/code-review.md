# Code Review Report

**Feature**: F022 默认部署与可选 BS Client 地址
**Review scope**: 本分支源码、部署、测试、规格/设计/任务及验证记录；自审，无多agent委派。
**Base branch**: feat/3.1.0-beta1 @ 0e975096fe
**Changed files**: 46

## Summary

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## Findings

### MEDIUM

- [Validation] 真实Nginx/Gateway、实际镜像下载和应用安装、MySQL/DM8及浏览器/Desktop普通用户全链路未执行。已有本地API/SQLite/密码学/SDK、实际Compose解析、Helm渲染与真实回环出口代理验证，以及待执行清单；上线前仍须在实际部署执行该清单。基线会话范围失败和外部数据库fixture问题已对照确认，未记作通过，见verification.md。

## 审查依据

- 空地址/空新配置块、新旧键整块优先、重复或非法Host、固定地址优先有测试。可信DNS解析异步且逐名称有超时，请求地址不写入共享配置。
- 登录PKCE、身份与令牌、原有权限和配额链路保留。浏览器来源继续严格核对；不可信转发头不能直接改变目标，Nginx边缘只信任声明的CIDR。
- SDK manager按请求建立和关闭；Server与ContextVar沿原模型复用，不临时改共享allowlist。并发不同Host的initialize、工具与技能调用通过。
- 配置仅保留一个canonical字段；兼容属性供原读调用使用。Helm使用null sentinel区分默认新键与显式新键，避免旧false被默认值掩盖。
- 独立运行身份密钥按安装生成，反复运行保持；现有.env、自管镜像/开关/来源保留。arch-guard既有Fernet常量warning没有被伪装为新增或通过。
- 默认PyPI/npm只进入准备阶段策略；私有源拒绝公网、应用运行期不开放包源由真实策略测试覆盖。没有绕过宿主/集群准入，没有新增SQL或权限旁路。
- design与实际实现、依赖、运行限制、验证结果同步；源码不代表镜像已发行或线上已生效。

## Overall: PASS_WITH_WARNINGS

源代码可提交供集成审阅；该结论不替代实机/发行验收。
