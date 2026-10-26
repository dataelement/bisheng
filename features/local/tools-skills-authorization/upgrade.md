# 上线与回退

此变更包含 OpenFGA 模型 f048-v6、权限目录发布和已有资源授权迁移。运行前备份 SQL、OpenFGA Store 和配置，记录原 CURRENT Catalog 与模型 ID。运行命令位于 src/backend，使用目标环境的 config 与依赖环境。

1. 停止 API、worker 与任务进程，等待 F048 runtime heartbeat 清空，完成正在进行的权限投影恢复。
2. 使用新版本执行 `PYTHONPATH=. python scripts/publish_authorization_model_change.py` 查看 dry-run。核对 Store、target checksum 和受影响目录。
3. 执行同一脚本，加上 `--apply --confirm-store-id <store-id> --confirm-target-model-checksum <checksum> --operator-id <operator-id>`。该步骤发布 v6 并在已有 tool 操作范围上加入技能作用域，保留自定义模型选择与等级策略。
4. 执行 `PYTHONPATH=. python scripts/migrate_capability_authorization.py --operator-id <operator-id>` 查看资源清单。Catalog 中需有启用、具备 use 且操作集合限于 use/download 的模型；缺失时先经目录发布流程配置。
5. 执行同一迁移命令，加上 `--apply --confirm-store-id <store-id>`。内置工具旧 user:* visible/system_use_marker 与所属租户成员 Grant 在同一持久投影内转换。已有企业技能补齐默认 Grant；个人技能沿用所属账户授权。
6. 再运行 dry-run，全部资源应显示 preserved。管理员后来撤销全员授权后，重跑迁移仍保留撤销结果。发生未完成投影时先恢复该操作，再重跑；脚本会停止并给出原因。
7. 启动全部新版进程，核对健康和权限版本。使用管理员与普通成员验证：全员可用 → 关闭全员并指定人员 → 撤销指定授权；核对工具菜单/调用、技能目录/直接下载/任务装载，以及跨租户与个人技能边界。

仅部署前端按钮无法完成此变更。模型、目录、数据迁移与进程版本须在同一维护窗口完成。

回退采用维护窗口下恢复匹配的 SQL/OpenFGA 快照、配置和旧进程版本。单独回滚代码会令模型校验失败。上线后已有业务数据时，先制定数据保留方案，再执行恢复。

本次 PR 提供脚本和单元/接口回归；生产迁移及真实账号验收由上线环境执行并留存报告。

根租户成员由当前 active UserTenant 快照生成请求级授权事实，与部门上下文一起传入 OpenFGA。上线核验应包含根租户普通成员的真实 use 检查；管理员操作入口单独验收。
