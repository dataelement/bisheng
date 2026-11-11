# F009 升级、盘点与回滚

术语说明：本文技术符号和英文状态值统一见[术语与缩写说明](terminology.md)；H为用户主属租户，M为当前管理目标租户。业务阅读可直接参阅使用中文全称的[影响范围与测试重点](../../../docs/reviews/managed-tenant-impact-test-focus-20261111.md)。

状态：操作说明，尚未在部署执行。已完成df927a7f6e发布线集成，当前唯一head为v310b1_merge_f009_release_heads；旧四列revision父链保留，新增空merge连接F118删除/work130，不用旧单head结论替代当前图。本批只增加三个既有表的四列，不新增业务表，不回填/搬迁/删除历史业务数据。需先完成隔离环境验收，不能把本地回归视为上线许可。

1. 保留旧版本应用/worker镜像与数据库备份；停止相关写入并排空旧文档/QA复制任务。旧消息没有本次精确关联或可信header，新worker会拒绝猜测执行。确认无在途外部写后再换worker。
2. 先对旧数据库做只读归属/旧COPYING核查；运行四列DDL：`flow.creation_state`、`t_gpts_tools_type.creation_state`默认READY，`knowledge.copy_source_id/copy_target_id`默认NULL。父head为`v310b1_f004_workflow_soft_delete`，经过四列revision升级至当前唯一head`v310b1_merge_f009_release_heads`；部署前重新确认发布线没有新的迁移head需要合并。MySQL/DM8均需集中验证。
3. 在四列已存在后运行新版只读脚本：从backend执行 `python scripts/managed_tenant_preflight.py --tenant-id <T> --user-id <U> --limit 100`。脚本需要新列，不能拿它直接扫描未迁移旧库。使用测试/部署既有安全配置，不复制凭据到日志。默认最多100人/每类资源，最高1000；truncated=true不能当全量盘点完成。UNKNOWN保持未知，FGA输出NOT_RUN需另核对。无apply。
4. 盘点当前H、原绑定/E、普通菜单/预算/审批标签、可选DSH、权限SQL镜像及pending/复制关联；旧READY默认不是完整权限证明。旧无关联COPYING标UNKNOWN_LEGACY_COPYING，名称相近不能证明同一复制意图。确认前不得自动补指针、迁移或清理。
5. API和worker同版本发布后，以专用数据完成e2e-checklist/QA；检查真实H与M、子表T和PENDING拒绝。受控创建恢复仅所属Service.resume_creation内部端口，要求原owner当前合法、固定T/资源/原key；FAILED_CLOSED不盲重放。没有新HTTP恢复中心或扫描任务。
6. 要回滚时先停止新版相关写入并证明worker及子任务结束，盘点/处理PENDING创建、当前copy_target_id占用和FAILED关联；旧版本不识别这些门禁。仅drop列不能安全取消在途任务或恢复权限，因此不得仅执行downgrade后直接开流。经人工核对、备份后，downgrade只删除四列，保留既有数据；不自动删资源、FGA tuple、文件或向量。

复制全过程自动续传、HTTP意图幂等、逐项manifest、未知外部写自动回收和跨系统强收敛均按scope-revision延期。正常失败保留可定位状态，人工处置应走原授权/删除流程，不能直接放行半成品。
