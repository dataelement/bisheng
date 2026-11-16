# 图像生成：本地验证与审查

日期：2026-11-09。分支：`codex/custom-web-search`；对照 `origin/main` 的工作区变更及未跟踪新文件。仅审查图像功能及共享接入，不将已有搜索改动计为新增图像逻辑。尚未提交。

## 自动验证

| 检查 | 结果与范围 |
|---|---|
| 后端组合回归 | 211 passed，9 subtests passed；8 条依赖弃用警告。涵盖图像、搜索、API 工具、执行权限、可用性和种子。 |
| 图像核心场景 | 11 个用例集中在 `test/tool/test_image_generation.py`；真实本地 HTTP、ASGI + SQLite，存储及授权外部边界使用替身。 |
| 前端现有测试 | `sharedSelection.test.tsx` 3 passed；模型保存、失败保留草稿和代码执行器原用例。 |
| 前端质量 | 全工作区 lint/typecheck、check-i18n、locales:check 通过；lint:prune 清除过期抑制项。 |
| Python / 架构 | 工作区变更 Python 文件 Ruff check/format 通过；架构守卫无输出违规。 |

后端命令：在 `src/backend` 设置 `config=/tmp/custom-web-search-test.yaml`，使用 `.venv/bin/python -m pytest -q` 运行 `test/tool/` 下的 `test_image_generation`、`test_custom_web_search`、`test_web_search_{deepseek,timeout,tool_config}`、`test_tool_api_{schema,nested_schema,transport}`、`test_tool_executor_{permissions,availability}`、`test_parse_preset_extra`、`test_preset_tool_{classification,seed_ids}`、`test_user_tool_availability`、`test_f048_tool_permissions`。

前端使用仓库规定的 pnpm 9.15.9。完整运行记录：`/tmp/image-generation-final-backend.log`、`/tmp/image-generation-frontend-test.log`、`/tmp/image-generation-{lint,typecheck,i18n,locales}.log`。

## AC 核对

- AC-01/06/07：新旧工具键共用工厂、保留旧调用名与默认模型，Azure 明确拒绝；种子和三语言名称同步。页面显示待人工验收。
- AC-02/10：本地 HTTP 验证自定义模型、规范化端点、Bearer 及仅发送 model/prompt；Executor 后续调用读最新配置。
- AC-04/05/12：真实保存 API/DAO 验证掩码 Key 保留、旧子项清空、无效配置不落库、普通用户和跨租户拒绝；执行权限拒绝时无上游请求。
- AC-08/09/11：URL/Base64、多图、无效响应、认证与存储失败；假 MinIO 验证调用方租户/用户目录，失败信息不含 Key。超时与响应大小限制经代码审查，未注入 180 秒超时或超大响应。

## sdd-code-review 自查

| 维度 | 结果 |
|---|---|
| 边界 | PASS：必填、旧配置、响应校验、超时和限量。 |
| 权限 | PASS（本地）：复用原权限入口；配置 owner tenant、执行当前授权和上传租户目录。真实 OpenFGA 待联调。 |
| 并发 | PASS：每次调用局部实例，配置不写回共享工具；分类/子项在同一事务保存。 |
| 信息泄漏 | PASS：复用 Key 掩码，历史子项脱敏，上游原始错误不外传。 |
| 测试 | PASS_WITH_WARNINGS：本地核心业务覆盖，真实部署端到端及页面未验证。 |
| 风格 | PASS：一个运行模块及一个新增后端测试文件；无 provider 框架、新表或新路由。 |
| 文档 | PASS：spec/design/tasks 同步当前协议、实现及验证限制。 |

整体：**PASS_WITH_WARNINGS（本地实现）**；不代表发布验收完成。修复了两条已有权限列表测试遗漏子键查询 mock 的回归，以及图像 bulk UPDATE 的显式租户条件。

## 真实环境验收清单（未执行）

本机 `http://127.0.0.1:7860/health` 无服务响应；本轮没有可用的真实上游与 MinIO 联调环境。

- [ ] `/build/tools` 显示通用名称；保存后重开正确回显，失败保留草稿。
- [ ] 既有应用无需重加工具；切换地址/模型后下一次生成使用新配置。
- [ ] 真实 URL/Base64 结果在聊天中展示；MinIO 链接可读取。
- [ ] 普通用户不能修改设置；撤销执行权限后拒绝生成。
- [ ] 旧 Azure 明确提示重新配置；重新填写后可使用兼容服务。

范围限制：单一 OpenAI Images 兼容协议；不自动发现模型或重试生成。Base64 图片链接沿用平台签名有效期，部分上传后失败可能留下孤立文件，本期不新增清理任务。
