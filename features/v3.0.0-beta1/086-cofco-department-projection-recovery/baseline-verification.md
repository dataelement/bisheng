# F086开发基线验证

目标origin/feat/cofco-1111-3.0.0-beta1，00720a9c697f55f19086fc7c7ad111986a95f4ac；独立工作区cofco-1111-department-recovery。2026-11-16。

现有定向回归53 passed：test_f048_department_projection、test_f048_department_scope_runtime、test_f048_projection_service、test_org_sync_reconciler。使用主工作区已有venv，目标worktree为cwd，config=/private/tmp/cofco-1111-department-tests-20261116.yaml（空配置），没有连接生产。

未改业务代码，未提交/推送/部署，未运行真实中间件集成。上述结果仅证明开发基线可测，不能证明新增自动恢复或手动脚本已实现。
