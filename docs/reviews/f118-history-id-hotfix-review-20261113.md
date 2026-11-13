# 历史准备脚本ID解析修复审查

日期：2026-11-13。基线为`origin/feat/3.1.0-beta1`的`36a9cc2833`，采用hotfix流程；对照F118 AC-115/116及design中的历史准备合同。本轮审查仅覆盖ID解析修复、回归和迁移流程说明，不是重新验收整个F118。

结论：**PASS_WITH_WARNINGS**。修复可进入beta1；目标镜像及真实MySQL/DM8旧库全流程尚未验收，不据本次通过恢复109业务。

| 维度 | High | Medium | 结论 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 显式模型/ID解析映射；未知类型、空值、非法整数不产生清理判断；真实10类主键存在/缺失覆盖 |
| 权限与认证 | 0 | 0 | 业务存在性仍按实际Owner表全局读取；外tenant已存在行保留；不增加共享或改动清理准入 |
| 并发/恢复 | 0 | 0 | 仅改变读参数解析；原pin、原值、下游、operation/version及同计划恢复围栏不改 |
| 信息泄露 | 0 | 0 | 无配置、凭据或业务备份进入Git；原CLI脱敏错误出口不改 |
| 测试覆盖 | 0 | 1 | 修复前6条稳定失败；修复后34历史准备、122组合通过；实镜像/真实中间件全流程待验证 |
| 代码风格/分层 | 0 | 0 | Owner组合仍在运维script，未移入permission仓库；Ruff检查/格式、arch-guard、diff-check通过 |
| 文档同步 | 0 | 0 | design与upgrade-guide补充修复及详细流程链接；9张Mermaid图沿实际代码标注查询、比较、写入和范围边界 |

## 修复内容

`business_models()`把每类Owner模型及`int`/`str`解析器放在同一映射中。`hard_missing()`取消`column.type.python_type`探测，真实查询Owner主键；不可解析ID保留，不把异常当作硬删除。

测试移除将Owner模型裁剪为Knowledge/KnowledgeFile的monkeypatch。新增三类AutoString资源进入完整capture的回归、全部10种resource_type的实际主键查询、外tenant已有行保留以及未知/非法ID不发SQL查询的用例。外部FGA传输仍隔离，不连接部署环境。

## 验证证据

- 修复前新增用例：6 failed、7 passed、16 deselected；失败均为workflow/assistant/app的`NotImplementedError`，含完整capture与直接存在性查询。
- 修复后`test_prepare_history.py`：34 passed。
- 7文件组合：122 passed，50.02秒，0 failed。存在既有SQLModel等弃用警告，不宣称零警告。
- 组合文件：`test_prepare_history.py`、`test_migration_cli.py`、`test_migration_cli_runtime.py`、`test_migration_inventory_application.py`、`test_migration_conversion_application.py`、`test_migration_preflight.py`、`test_migration_source_lifecycle.py`。
- 组合测试执行于2830f103e9加本次修复；交付前合入36a9cc2833。新增远端差异仅涉及app-proxy及插画，迁移代码、测试及其依赖未变，未据此重复整组选集。
- `prepare_f118_history.py --help`在backend根目录执行通过；不初始化迁移运行时。
- Ruff check及format --check通过；两个Python变更文件arch-guard无输出；git diff --check通过。
- 流程文档相对源码链接全部存在，Markdown代码围栏闭合，共9张Mermaid图。未执行独立Mermaid渲染器的图形验收。

待验证的Medium项应使用固定新镜像及未迁移快照，实际执行历史准备preview与后续M2/M3/M4及同Run恢复；116已迁移结果复核不能替代。此审查未登录或修改116/109，未处理任何现场阻塞数据。
