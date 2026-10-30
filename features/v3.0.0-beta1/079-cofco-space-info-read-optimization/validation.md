# F079 本地验证记录

日期：2026-10-30。基线：`a0bf4205f0070b83f4780ceafc25fd0e99b62401`，目标 `feat/cofco-1028-3.0.0-beta1`。

## 自动化结果

- 修改前：`test/knowledge/test_knowledge_space_service.py` 15 passed。
- 修改后：下列专项回归 **105 passed、11 skipped**，无失败。7 条依赖弃用等警告与基线一致。
- 跳过的 11 项来自新建真实环境 E2E 套件，未设置 `COFCO_INFO_E2E=1`；本次没有部署或连接客户/109 环境。
- Ruff check / format check：5 个变更 Python 文件通过。
- Architecture guard：5 个变更 Python 文件无输出违规。
- `git diff --check` 及 `git diff --cached --check` 通过；暂存清单仅含本次 13 个文件。

使用本机已安装的 Python 3.11.13、pytest、Ruff 0.15.14，工作目录为隔离工作区的 `src/backend`。通过临时 YAML 指定 SQLite 内存数据库和不可用的本地 Redis 端口，外部 I/O 由测试 fixture 替换；未复制部署凭据或修改共享配置。

运行的测试文件：

```text
test/knowledge/test_knowledge_space_service.py
test/knowledge/test_knowledge_space_info_optimization.py
test/knowledge/test_space_joined_visible_ids.py
test/knowledge/test_joined_spaces_permission_sources.py
test/knowledge/test_f048_preview_download_permissions.py
test/knowledge/test_space_listing_pin_source.py
test/permission/test_f048_application_adapters.py
test/permission/test_data_scope_enforcement.py
test/permission/test_f048_action_catalog_policy.py
test/permission/test_disabled_catalog_action_listing.py
test/cofco/test_cofco_config_customizations.py
test/e2e/test_e2e_cofco_space_info.py
```

## 已验证的行为

普通有效成员只进行入口 visible 单动作校验，不调用 `_get_effective_actions`；无成员记录的可访问者保留 manage_permission 角色判断。pending/rejected 与可见权限并存时，info 与广场均显示 subscribed，成员记录不变。

公开/审批预览保留申请状态和空 actions；私密、未发布、不存在及鉴权异常继续抛出原错误。超管无真实授权时可访问而未加入；下载开关、创建者、统计字段及重建租户守卫保留。

全部十个计时阶段的失败用例验证异常传播、失败阶段及已耗时间；成功用例验证单条终态、阶段时长非负及计时不重叠。

## 尚未验证

真实 JWT/OpenFGA/达梦联调、浏览器跳转和按钮体验、生产冷启动及 P95 改善需部署后按 [e2e-checklist.md](e2e-checklist.md) 验收。未改前端源码，本地前端测试与构建遵循中粮分支约定交由镜像构建阶段，不宣称通过。
