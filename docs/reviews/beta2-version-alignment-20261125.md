# 3.1.0-beta2 版本一致性审查

日期：2026-11-25。目标：`feat/3.1.0-beta2`。基线：`d2097d6be823d0f64501a94a967a5d8678922c71`。

## 修改范围

- Backend、Runtime Manager、App Proxy 的项目元数据和 `__version__` 统一为 `3.1.0-beta2`；三个 uv.lock 仅修改本项目条目，使用 PEP 440 规范化值 `3.1.0b2`。
- App Proxy 的 ASGI 应用版本引用包版本；helper/assembler 清单中的 runtime-package 更新为 beta2。清单工具保留直接按文件执行的方式，不新增包安装或 PYTHONPATH 前提。
- Compose 五个产品服务的镜像默认值、三个 Chart 的 appVersion、父 Chart 与沙箱子 Chart 的产品镜像标签统一为 beta2，并同步当前安装说明和沙箱构建示例。
- update.sh 更新目标版本并覆盖当前产品元数据、部署默认值及打包用例；锁文件只更新本项目，不修改第三方依赖。前端质量工作流增加 beta2 push 触发，保留 beta1 触发。
- Platform、Client 的 package.json 已是 beta2，无需修改。

## 保留项

CLI、SDK、共享前端组件、FT、Gateway、中间件及二进制工具保持各自版本；Chart 自身的 `version: 0.2.0`、依赖版本及 Chart.lock 保持不变。历史 feature 文档、迁移目录、Alembic revision 和历史版本兼容标识均未修改。

## 验证

在隔离工作树中使用已有 Python 3.11 环境和校验过官方 SHA-256 的 Helm 3.17.3：

| 范围 | 结果 |
| --- | --- |
| scripts/tests/test_standard_helm.py、test_helm_package.py | 47 passed |
| src/runtime-manager/tests/test_image_release.py | 42 passed |
| src/app-proxy/tests/test_entrypoint_smoke.py | 3 passed |
| 项目元数据、包版本、ASGI 版本、运行时清单版本 | 一致 |
| 三个 uv.lock 与基线逐项对比 | 除本项目版本外完全一致，第三方依赖及哈希未变 |
| Compose、Chart appVersion、产品镜像标签、前端包版本 | beta2；独立组件版本保留 |
| update.sh 临时副本执行 | 从其他目录执行及重复执行通过，排除文件未变 |
| ruff check、bash -n、git diff --check、变更文件 arch-guard | 通过，无架构守卫输出 |

涉及本机临时 HTTP/WebSocket 服务的测试在沙箱外运行；没有调用真实镜像构建、推送或集群部署。

## Code Review Report

**Review scope**：24 个实现、配置和说明文件及本审查记录；按 trivial 修复流程核对完整差异。

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

仅调整版本及维护脚本，不改变鉴权、事务、业务协议或数据库结构；当前安装说明已同步。无待修复发现。

**Overall: PASS**
