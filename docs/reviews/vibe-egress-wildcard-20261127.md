# Vibe 通配出网域名上线失败修复自审

日期：2026-11-27。目标分支：`feat/3.1.0`。检查基线：`9c08cf909ee47743b071f032f8ca1dbd9791ccf6`。

## 问题与最终行为

应用清单声明的 `*.hdslb.com` 等域名被后端出网授权解析器拒绝，正式启动在创建容器前收到 `egress_destination_invalid`；预检未携带域名声明，因此先前能够通过。

修复后，后端将前缀通配符归一化为代理既有的 leading-dot zone；保留端口和 `trusted=false`，精确域名仍为精确域名，裸星号、空域名段、非前缀通配符与声明中的账号密码继续拒绝。预检传递同一份业务域名声明，仍使用隔离数据与预检身份。设计同步见 `features/v3.0.0/086-vibe-runtime-delivery/design.md` §4.10、§5、修订历史。

本次为既有合同的 hotfix，未新增接口、数据库结构、依赖或业务权限。不修改生产环境。

## 七维自审

按 `.claude/skills/sdd-code-review/SKILL.md` 执行本地自审；不是独立审查或生产验收。

| 维度 | High | Medium | Low | 结果 |
| --- | --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 0 | PASS：覆盖真实失败域名、大小写、HTTP/HTTPS、显式端口、非法通配符 |
| 权限与认证 | 0 | 0 | 0 | PASS：zone 保留非可信标记，预检凭据隔离；代理现有拒绝策略不变 |
| 并发安全 | 0 | 0 | 0 | PASS：未改变事务与凭据派生，重复签发稳定性回归通过 |
| 信息泄漏 | 0 | 0 | 0 | PASS：只读策略仍不包含明文凭据，回归检查 token 不外泄 |
| 测试覆盖 | 0 | 0 | 0 | PASS：解析、实际 SQLite 落库/投影、预检传递、代理隔离回归 |
| 代码风格 | 0 | 0 | 0 | PASS：Ruff、格式检查、架构守卫及 diff 检查 |
| 文档同步 | 0 | 0 | 0 | PASS：同步原设计与已知坑，明确部署边界 |

## 验证证据与限制

- 修复前新增回归组合：9 failed、8 passed；覆盖生产四个通配域名被拒及预检遗漏域名。修复后同组：17 passed。
- Runtime Manager：`tests/test_egress.py tests/test_platform_egress.py` 为 80 passed、4 skipped。包含本机回环代理测试；首次沙箱不允许绑定端口，使用获准的本地测试权限后重跑通过。没有访问生产执行测试。
- 后端扩展组合（出网新测试、生命周期、协调器）：修复后 29 passed、14 failed；未修改的独立基线同一已有文件组合为 13 passed、14 failed。JUnit 失败用例集合完全一致，无新增失败。
- 14 项基线失败来自 `test_runtime_lifecycle_v2.py` 两项及 `test_runtime_k8s_delivery_coordinator.py` 十二项，涉及旧构建标记、失败映射、准备 profile 和预览身份测试；未将它们改成跳过或放宽断言，未宣称扩展组合全绿。
- 四个改动 Python 文件的 Ruff 检查、格式检查、逐文件 `scripts/arch-guard.sh`、`git diff --check` 均通过。
- 未执行完整中间件/MySQL/DM8、Docker/Kubernetes 真实部署或生产重新发布。代理四项跳过仍保持原测试条件。

## Overall: PASS

结论只适用于本次 hotfix 及上述验证范围。生产应用仍需待后续部署修复版本后再重试上线。
