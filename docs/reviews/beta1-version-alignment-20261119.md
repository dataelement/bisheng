# 3.1.0-beta1 版本一致性审查

日期：2026-11-19。目标：`feat/3.1.0-beta1`。基线：`7a7a26ed26`。

用户确认应用版本为 `3.1.0-beta1`，镜像标签为 `v3.1.0-beta1`。

## 调整范围

- Backend、Runtime Manager、App Proxy 的 pyproject 和 `__version__` 统一为 `3.1.0-beta1`，各自 uv.lock 的本项目条目使用 PEP 440 规范化值 `3.1.0b1`。
- Client 包版本统一为 `3.1.0-beta1`，与已有 Platform 包版本一致。
- update.sh 的旧值/目标值更新为 `3.0.1-beta1` → `3.1.0-beta1`。
- 五个应用镜像标签保持已确认的 `v3.1.0-beta1`，Helm appVersion 已为 `3.1.0-beta1`。独立 SDK/CLI、共享组件包及 Chart 包自身的版本不属于本次平台版本同步范围。

## 七维审查

| 维度 | 结论 |
|---|---|
| 边界条件 | PASS：标准预发布版本；锁文件采用规范化格式 |
| 权限与认证 | PASS：未改授权逻辑 |
| 并发安全 | PASS：未改业务执行逻辑 |
| 信息泄漏 | PASS：仅公开版本元数据，无凭据变更 |
| 验证覆盖 | PASS：三项目离线锁校验与结构化一致性检查 |
| 代码风格 | PASS：Ruff、架构守卫和差异空白检查通过 |
| 文档同步 | PASS：本记录描述版本格式与调整边界，无业务契约变化 |

## 验证

- Backend、Runtime Manager、App Proxy 分别执行 `uv lock --check --offline`，全部通过。
- 解析 TOML、JSON 并执行版本声明，确认三个 Python 包的源码/元数据/锁文件一致，两个前端应用版本一致，五个应用镜像标签符合用户确认值。
- 与基线解析结果逐项比较，去除本项目 version 后，三份 pyproject/uv.lock 完全一致；没有新增或升级依赖。
- 三个修改的 Python 文件 Ruff format/check、逐文件 arch-guard、`bash -n update.sh` 和 `git diff --check` 通过。
- 仅版本元数据调整，未新增测试。未构建或发布镜像，未部署环境。

总体：**PASS**。
