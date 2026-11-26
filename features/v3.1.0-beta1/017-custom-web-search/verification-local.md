# 本地验证记录

本记录汇总本轮已报告的局部自动化结果，不代表功能或 SDD 任务验收完成。

## 后端（核心测试收敛后）

- 新增功能的测试、fixture 和 helper 合并到 `test/tool/test_custom_web_search.py`，保留 **21 个功能用例**；覆盖范围见 [任务清单](./tasks.md)。
- 从 `src/backend` 执行以下组合回归：**128 passed、7 warnings**，包含原有 provider 和工具 API 回归。

```sh
config=/tmp/custom-web-search-test.yaml .venv/bin/python -m pytest -q \
  test/tool/test_custom_web_search.py \
  test/tool/test_web_search_deepseek.py \
  test/tool/test_web_search_timeout.py \
  test/tool/test_web_search_tool_config.py \
  test/tool/test_tool_api_schema.py \
  test/tool/test_tool_api_nested_schema.py \
  test/tool/test_tool_api_transport.py
```

- 本地使用 Python 3.12、项目 `.venv`、空测试 YAML、SQLite 和项目原有外部服务 mock；集成主链路访问本地受控 HTTP 上游，并经过实际隔离传输。
- 已删除独立密码学/TLS/网络变体矩阵、前端逻辑 Python 副本、通用 Worker 上下文和占位 E2E 测试；上述通过数不包含这些覆盖。

## 前端与部署配置

- 使用 pnpm 9.15.9 执行 `pnpm --dir src/frontend lint` 与 `pnpm --dir src/frontend typecheck`，全量检查通过；platform `lint:prune` 通过。两个组件测试已按用户要求删除。
- `docker-compose -f docker/docker-compose.yml config --no-interpolate --quiet` 配置语法检查通过；Docker daemon 不可用，因此未验证容器启动或实际部署。

## 验证边界

- 上述结果不是真实前后端端到端测试，不证明实际用户入口、真实服务调用或完整引用链已经验收。
- SQLite 和 mock 环境不能替代 MySQL、DM8 的建表、事务及并发验证；也未验证真实跨进程 broker、权限服务及其部署集成。
- SDD 各任务尚未逐项核对及完成对应审查；设计、任务、E2E 和特性级审查状态以 [任务清单](./tasks.md) 为准。不得根据本记录勾选任务或声称审查完成。

## 2026-11-15 P1 修复验证

- 本地 search/tool-config/timeout 三组回归共 33 项通过，Ruff 与架构检查通过。新增用例在两个专用密钥变量缺失时执行，并验证 8 个并发初始化者共享密钥、用途/租户绑定、损坏记录拒绝和旧 key ID 可解密。
- 115 原有 1 条凭据已迁移为 platform 加密密文并解密通过；backend/worker 已重建，实际容器和 env_file 均移除两个变量，worker 也验证原凭据可解密。
- 115 使用原已保存配置直接调用 search_preview 成功，返回 38 条结果。此为服务器 Service 调用验证，不等同于已登录界面操作或完整 Desktop 会话验收。
- 部署只替换搜索密钥加载部分，保留线上已有的 OpenAPI v2 实现；服务器窄补丁不代表整个 PR 已部署。
# 2026-11-24：beta2 移除操作 proof

本节仅覆盖本次定向修改；起点 `origin/feat/3.1.0-beta2` / `3168b8724b`。不代表整个 F017 或生产环境完成验收。

- 修改前：`test_custom_web_search.py` + `test_openapi_search.py`，34 passed。
- 修改后：上述两文件，加 `test_parse_preset_extra.py`、`test_tool_executor_permissions.py`、`test_tool_executor_availability.py`，55 passed，9 subtests passed。
- API 链路：通过真实 FastAPI 路由进行导入 → 保存 → GET 重读 → 携带旧 proof 的测试调用；使用 SQLite 隔离持久化，身份依赖替身及固定上游响应。另有回环 HTTP 服务覆盖导入 → 保存 → ToolExecutor → 隔离请求执行。未执行远端部署 E2E。
- 复制兼容：目标租户的缺失、过期和畸形旧 proof 均不影响读取、预览、保存和工具构造；返回值及 custom 保存结果不含 proof，运行初始化不修改 ORM 配置。其他租户访问仍 404。
- 前端：`CustomWebSearch.test.tsx` + `SharedToolSettings.test.tsx`，2 文件 / 16 passed，覆盖导入无 proof、直接保存已有配置及原设置交互。
- 前端全量 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n` 通过。lint 有既有 `BatchTagDraftDialog.tsx` 未使用 eslint-disable 的 warning；没有 error。测试使用现有安装依赖，并将 workspace 包指向当前 beta2 源码，未改锁文件。
- 四个修改 Python 文件的 ruff format/check 通过，`git diff --check` 通过。架构守卫没有 VIOLATION；`test_openapi_search.py` 的原有合成 Bearer 凭据触发 RULE-7 warning，不是真实凭据。
- 未部署生产，未执行 MySQL/DM8、真实搜索凭据或完整生产 PPT 任务。部署后的人工验证见 e2e-checklist.md 的 beta2 回归部分。
