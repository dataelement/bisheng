# 自己做的决定

按 goal-runbook §4"自己定"处理的事项，每条一行：任务号｜遇到什么｜怎么定的｜为什么。

- T001｜worktree 软链的是主检出的 `.venv`，`uv run` 默认会按本 worktree 的 lock 同步这个共享环境｜后端测试一律用 `uv run --no-sync python -m pytest`（清代理六变量）代替 `uv run pytest`｜不改共享环境；`-m pytest` 让 `import bisheng` 解析到 worktree 代码而不是主检出的 editable 安装
