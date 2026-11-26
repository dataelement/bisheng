# E2E — Developer Token sync records (086)

独立验收清单（真实环境；研发期未自动执行）。

## 前置

- 已跑 Alembic `f124_filelib_sync_run_log_error_text`
- 管理员可进 Platform「开发者 Token」
- 至少一个 Token 已配置文件同步；可选汽车板已绑定同一 Token

## 检查项

1. Token 行「编辑」旁有「同步记录」；点开弹窗可分页，列含接口 / 触发 / 状态 / 文件名 / 时间 / 耗时 / 错误。
2. 用该 Token 调一次失败的 `POST /api/v2/filelib/file/sync`，同步记录出现 `failed`、`trigger=api`、接口文案可区分汽车板。
3. 错误超长时详情可打开、可复制；文末可有 `[truncated]`。
4. Token 列表上方不再出现「汽车板介绍同步」配置区；汽车板历史仍可在关联 Token 的「同步记录」中查看。
5. retrieve / 非同步接口失败不新增同步记录行。
