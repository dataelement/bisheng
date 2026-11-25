# 解除租户挂载的权限迁回修复

日期：2026-11-24。目标发行线：`feat/3.1.0-beta2`，初始基线 `ee270ee122`。
用户范围：修复解除挂载的代码缺口，核查其他资源，提供通用运维脚本，并修复 116 本批历史数据；按最小改动保留现有接口，不新增后台任务系统/进度页面。

## 根因及影响

旧 `TenantMountService.unmount_child` 只经白名单批量重写业务 tenant_id，未迁移 F048 模式、Grant、assignee 和 visible-source。权限加载按业务实际租户查找，因此旧台账即使 CURRENT 仍报 10994。FGA 的 Grant 节点键由 tenant/type/id/model 派生，单改 SQL 仍会不一致；旧 FINALIZED 及 CURRENT 状态不会触发跨租户自动恢复。

116 审计确认：租户 18 于 2026-11-12 解除挂载，业务资源迁回 Root 后权限留在 18。同批错位为 32 个资源：助手 2、工作流 3、自建工具 2、频道 5、知识空间 5、QA 库 1、文件 14。原租户的 16 个预置工具未迁移，符合既有排除规则。

## 最小修复及决策

- 服务原接口仍仅允许已验证超管。原解除挂载迁移函数委派 `ResourceTenantTransferApplication`，根据原业务白名单及真实行类型展开精确范围。内部 Flow/退役私有库不猜权限类型，预置工具继续排除。
- 事务内锁定并重验源 Child、业务闭包、CURRENT Catalog 和权限快照，写入原生 `RESOURCE_TENANT_TRANSFER` 投影操作及元组，**同一 SQL 事务**迁移业务归属和四类权限镜像。源 Child 在该事务中暂时停用；SQL 失败全部回滚。
- FGA 复用现有 STAGE/COMMIT、版本/operation fence、原记录恢复、高一致校验及 SQL finalizer。STAGE 停用资源技术标记并调整旧/新 Grant 节点，原子 COMMIT 更换资源 Grant 绑定并恢复技术标记；成功后 mode 为 CURRENT、版本 +1。只有全部成功才继续原 Child 归档、成员重算和租户关系清理。
- 模式、父级、所有者、授权模型和来源、ID/指纹、visible/public/shared 谓词保留。旧 `tenant:child#member` 不自动扩成 Root 全员。旧投影操作/元组及审计不重写。
- 拒绝目标冲突、非 CURRENT 来源、进行中投影、未知物理 Grant/来源、可见性/模式/父级不符以及快照或 Catalog 变化。权限模块不读取业务 ORM；业务归属由 tenant 所有者核验，权限 owner 只参与同一原生事务。

选择复用已有投影台账，而非新建解除挂载任务框架或直接 UPDATE-only 修数据。现有 HTTP 仍同步执行，大租户可能超时；重试原解除挂载先续办原台账。失败后的源 Child 可保持 disabled、部门挂载不清，等待原请求续办；这不是全流程后台化，也没有自动强行改成成功。

## 通用运维工具

`src/backend/scripts/repair_unmounted_tenant_permissions.py` 与环境无关，参数指定旧 Child、当前超管操作者、私有 plan 文件及确认摘要。默认只读预览并以 0600 独占创建 SQL/FGA 完整 before 备份；apply/resume 使用相同原生迁移及投影流程，不绕过业务边界。只接受已归档、有解除挂载审计、实际业务归属 Root 而权限仍在旧 Child 的精确对象，不修未知迁移、不授新权限。目标冲突或不完整历史需人工核实。

脚本初始化和关闭自己拥有的 DB/Redis/FGA 客户端，复用服务 settings 和 CURRENT pin，不发布模型或重置整个 namespace。所有选中 SQL 来源字段与物理对象均完整验证，并读回权限版本；不以抽样替代完整性核验。运行方法见 scripts/README.md。没有新表/DDL/依赖或前端修改。

## 验证

定向组合 69 passed：

```text
test/tenant/test_resource_tenant_transfer.py
test/tenant/test_tenant_unmount_service_transaction.py
test/tenant/test_tenant_unmount_dialect_compat.py
test/permission/test_f048_projection_service.py
test/permission/test_f048_projection_sql_runtime.py
```

原生 SQLite + 原生投影 journal/finalizer 覆盖 SQL 回滚、源/目标冲突、权限/业务快照变化、pin 漂移、未知物理来源、事务提交后崩溃、FGA 失败沿原记录恢复、幂等续办、授权对象不扩张、全部资源类型映射、历史 JSON 计划重读及通用 CLI 完整验证。物理 FGA 传输在本地隔离，现场另有真实存储验证。

旧 `test_tenant_mount_service.py` 六项失败在未改动 `ee270ee122` 的同文件组合原样复现（基线 22 passed/6 failed，初次候选加八项新用例为 30 passed/相同六项失败）。原因包括旧 mock 未接创建 owner、归档事务及策略清理，以及旧“同步失败吞掉”断言；本次不为让套件全绿改动已确认行为。

规模用例测量同一 preview/apply/verify/no-op resume 路径，实际资源 4→8：SQL 187→363、事务 44→84、完整对象读取 36→72、物理写批 8→16；本地峰值约 0.93→1.08 MB、耗时约 147→267 ms。按真实资源/来源线性处理，无用户×资源枚举；这些本地数字不代表生产维护窗口或大型租户容量承诺。无变化路径不新增投影或写 FGA。

## 116 执行与验收

使用同一通用 CLI，候选仅暂存在容器私有 `/tmp/bisheng-unmount-repair-20261124`，未替换在线应用源码、未重启服务。

- 只读预览精确选中 32 个对象并核验旧/新 Grant 物理图；摘要 `1540040baae30fb9122e0581d90edd5973e9507a8520e0765f6bf7dbca339c56`。
- 完整修复前私有备份已保存在宿主机 `/root/bisheng-repairs/tenant18-20261124/before.json`（0600），包含原始 SQL 来源和完整受影响 FGA 对象；容器内另保留 preview 文件。
- apply 返回 `state=verified, resource_count=32`。全量 SQL 来源/模式/版本及物理图 after 均与原授权意图一致；技术标记、父级和可见性保持。备份另离线核验 32 个对象的可见性/模式/父级均无原始矛盾。
- 最终交付版本的通用 CLI 使用同一计划再次执行 `--resume`，返回相同 `verified / 32`；没有重复迁移，完成全量 SQL/FGA 和权限版本读回。
- 指定助手 `da7e19d185714b3991153dee45bb9ba2` 的实际业务加载器及原生 `my-permissions` 应用链路回读成功：CUSTOM、CURRENT、projection_degraded=false，返回有效管理动作；原所有者 user:682 的实际 FGA can_edit=true。

这证明本批数据已恢复；不表示未来解除挂载代码已经部署到 116。代码交付通过发行线提交，新建解除挂载需部署该版本才能使用修复后的路径。

## 七维审查

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

**Overall: PASS。** 保留同步接口与原请求续办边界，原生事务/投影约束不被脚本绕过，未修改原授权受众或其他 agent 处理的助手运行问题。MySQL 实际本批修复完成；DM8 本机不可运行，代码使用通用 SQLAlchemy 类型/语句，不宣称已通过真实 DM8 集成。
