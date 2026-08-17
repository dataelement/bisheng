# F048 E2E 手工与运维验证清单

> 2026-07-30：用户确认本地不执行真实环境 E2E。本清单作为后续目标环境发布验证参考，
> 不属于本次“功能与迁移脚本开发完成”的验收范围。

> 状态：待在专用 F048 集成环境执行
> 数据前缀：`e2e-f048-permission-`
> 安全要求：禁止连接生产；禁止删除此前缀之外的任何数据。

## 0. 2026-08-13 可见性增量必验矩阵

以下场景是本次单槽 `visible` 增量的发布门禁，不能被后文旧 F048 通用清单替代：

- [ ] 创建五个由他人创建的知识空间，分别通过 direct user、department userset、
  user-group userset、主动订阅迁移来源和 system/shared Owner 来源授权同一普通用户；
  `GET /knowledge/space/joined` 返回五个空间且不依赖 `space_channel_member` 行或成员角色。
- [ ] 同一用户创建的空间即使存在 `visible` 也不出现在 joined；平台超管和租户管理员使用
  相同账号来源集合时结果与普通用户一致，不因管理员身份扩展到全部空间。
- [ ] 为同一知识空间制造 direct + department + group 多来源；逐个撤销时，前两个撤销不删除
  聚合 `visible`，最后一个来源撤销后 Check、BatchCheck 和完整枚举才同时变为不可见。
- [ ] 停用仍被引用的自定义模型：已有成员的 visible、具体 action 和
  `manage_permission` 不变；ADD/MOVE 目标不再包含该模型，Platform/Client 既有行仍展示并可
  MOVE/REMOVE。删除不要求先停用，但引用或 projection/live residual 非零时返回 25004。
- [ ] 部门空间列表先查询部门绑定得到有限候选空间 ID，只执行一次分块 BatchCheck；不先枚举
  全平台知识空间，也不重复逐项 visible 校验，响应不返回 `manage_permission` 或部门元数据。
- [ ] 文件列表按业务排序跨至少三批取候选并 BatchCheck；首批可见项不足时继续扫描，填满页面
  后 cursor 指向最后消费候选，下一页无重复/遗漏；父空间可见不能替代子项最终 visible。
- [ ] 为一个用户准备 5,001 个知识空间 visible 结果，joined 返回明确容量错误，不返回 200
  截断集合；4,000 个结果触发 80% capacity 告警指标。
- [ ] 在 StreamedListObjects 输出部分结果后断开连接，joined 整体失败且
  `stream_completed=false`；停止 OpenFGA 后 Check/BatchCheck/list 均不从 SQL、旧 binding、
  creator 或管理员身份回退产生 ALLOW。
- [ ] 校验 `permission_visibility_projection` 与 `permission_visible_list` 指标包含 source/tuple/
  checksum/stale/orphan、strategy/candidate/visible/scanned/amplification/capacity 和各阶段耗时，
  且不包含姓名、资源名、Config 原文或 token。

## 1. 环境与账号

- [ ] API、Platform、Client、Worker、Linsight Worker 使用同一构建版本。
- [ ] OpenFGA 为 `openfga/openfga:v1.15.1@sha256:<approved-digest>`；配置只保留
  连接信息和稳定 Store name，未写 Store/model/Catalog ID。
- [ ] API、Worker、Linsight、同步任务的 heartbeat 均报告同一
  `store_id`、`authorization_model_id`、`catalog_release_id` 和 model checksum。
- [ ] `OPENFGA_RESOLVE_NODE_LIMIT`、ListObjects 上限、RPC histogram 和 JSON
  日志已按部署清单启用。
- [ ] 准备平台超管、同租户普通用户、另一租户普通用户；普通用户无平台超管、
  租户管理员或其他系统级资源豁免。
- [ ] 设置 `E2E_API_BASE`、`E2E_ADMIN_PASSWORD`、`F048_E2E_USER_ID`、
  `F048_E2E_USER_NAME`、`F048_E2E_USER_PASSWORD`、
  `F048_E2E_CROSS_TENANT_USER_NAME`、
  `F048_E2E_CROSS_TENANT_USER_PASSWORD`。

## 2. 真实 API 场景

- [ ] 执行：

  ```bash
  cd src/backend
  F048_E2E=1 \
  E2E_API_BASE=http://<host>:7860/api/v1 \
  E2E_ADMIN_PASSWORD='<secret>' \
  F048_E2E_USER_ID='<same-tenant-user-id>' \
  F048_E2E_USER_NAME='<same-tenant-user>' \
  F048_E2E_USER_PASSWORD='<secret>' \
  F048_E2E_CROSS_TENANT_USER_NAME='<cross-tenant-user>' \
  F048_E2E_CROSS_TENANT_USER_PASSWORD='<secret>' \
  .venv/bin/pytest \
    test/e2e/test_e2e_f048_permission_model_grants.py -v
  ```

- [ ] 6 个测试全部通过，无 skip。
- [ ] 运行前后的 `e2e-f048-permission-*` 工作流数量均为 0。
- [ ] 非测试工作流、Grant、Catalog、用户和租户的数量及 checksum 未变化。

## 3. Platform Catalog

覆盖 AC-01～18、AC-64、AC-148～149、AC-156。

- [ ] 平台超管进入“系统管理 → 角色与权限 → 资源权限”，可看到动作等级与模型管理。
- [ ] 非平台超管看不到该入口；直接请求 `GET /api/v1/permissions/catalog`
  返回业务错误 `19000`。
- [ ] 动作面板同时显示“未分配”和 1～4 级五个区域；每个动作只出现一次。
- [ ] 新动作默认在“未分配”，在分级前不出现在模型动作和正式授权结果中。
- [ ] `view_space`、`view_folder`、`view_file`、`view_channel`、`view_app`、
  `view_kb`、`view_tool` 不再出现。
- [ ] 调整一个动作的 level 后，影响页展示资源数、Grant 数、主体来源数、
  扩权数和撤权数。
- [ ] 取消确认时当前 Catalog release 不变。
- [ ] 确认发布后，四个标准模型以及全部自定义模型的派生等级、动作适用范围
  在同一 release 内整体更新。
- [ ] 两个管理员基于同一旧 release 发布，只有首个成功，第二个返回 `25002`。
- [ ] 查看者/编辑者/管理者/所有者的 key、名称、等级、动作集合不可编辑或删除。
- [ ] 标准模型仅在包含 `manage_permission` 时显示“允许授予同级”开关。
- [ ] 自定义模型的等级由最高动作自动得出；空动作、未分级动作或越界动作无法保存。
- [ ] 停用仍被 Grant 引用的模型后，不能再用该模型新增或变更授权，但已有 Grant 的可见性、
  具体动作和 `manage_permission` 保持不变；引用未清零时删除返回 `25004`。
- [ ] 逐项撤销或替换全部 Grant/assignee 后，source projection 与 live visible tuple 对账为零，
  此时允许删除模型；停用不是删除前置条件。
- [ ] 模型发布前后既有 Grant ID 与 assignee 数不因动作变更发生 fan-out 重写。

## 4. 两端成员与模式界面

覆盖 AC-19～27、AC-36～65、AC-150～152、AC-157。

对 workflow、assistant、tool、channel、dashboard、knowledge_space、
knowledge_library、folder、knowledge_file 逐类执行：

- [ ] 权限弹窗展示 `CUSTOM`/`INHERIT`、是否可切换及直接父级名称。
- [ ] 成员行展示主体类型、名称、模型、等级、本级/继承、直接/部门/用户组来源、
  `include_children` 和受保护状态。
- [ ] 创建者 owner 为受保护行，不可删除或降级；可以新增多个普通 owner。
- [ ] 不存在“转让所有权”入口或旧 owner transfer API。
- [ ] 用户、部门、包含子部门的部门、用户组授权各创建一次；重复请求保持幂等。
- [ ] 同一用户通过直接授权和部门/用户组授权获得不同模型时，来源明细分别保留，
  有效动作取并集。
- [ ] 仅撤销直接授权后，部门/用户组来源继续有效。
- [ ] 普通成员只能看到最小化的“我的权限”，不能读取其他成员 roster。
- [ ] 可授予模型列表只包含当前每个 `manage_permission` 来源独立允许的模型；
  不把一个来源的 level 与另一个来源的动作拼接。
- [ ] 修改/撤销请求使用 assignee version；过期版本返回 `25002`。
- [ ] `INHERIT` 成员为只读并标注来源；不能新增、修改或撤销普通本级 Grant。
- [ ] `INHERIT → CUSTOM` 先展示快照影响，确认后保留主体、模型、范围和来源。
- [ ] `CUSTOM → INHERIT` 先展示删除影响，确认后仅删除普通本级 Grant，
  保留受保护 owner。
- [ ] 用户在确认弹窗取消后，模式、Grant、FGA tuple 和 resource version 均不变。
- [ ] knowledge_space 与 knowledge_library 固定为 `CUSTOM`，无 `INHERIT` 入口。
- [ ] 文件夹/文件创建后默认 `INHERIT`；业务移动后继承新的 canonical parent。

## 5. 资源动作矩阵

覆盖 AC-28～35、AC-69～70、AC-153～155。

- [ ] 每种资源分别用 viewer/editor/manager/owner 与一个自定义模型验证全部适用 action；
  断言使用具体 action，不使用旧 relation 或通用 `can_view`。
- [ ] workflow/assistant 的列表、详情、使用、编辑、删除、分享和权限管理均由对应
  business Service 先解析业务事实，再调用 F048。
- [ ] tool 的列表、详情、执行、编辑、删除和权限管理使用同一运行时。
- [ ] channel 的列表、文章详情、订阅操作和权限管理使用同一运行时。
- [ ] knowledge_space/library/folder/file 的列表、详情、上传、编辑、删除、分享、
  下载和权限管理使用同一运行时。
- [ ] 权限包不能通过仅有“可见性”的候选结果证明 edit/delete/download/share/use。
- [ ] 权限模块 SQL/日志中不出现业务资源表查询；tenant、状态、parent 均来自
  `VerifiedPermissionTarget`。

### Dashboard

- [ ] 新建 dashboard 仍只受既有菜单能力控制，并生成受保护 owner。
- [ ] 列表、详情、组件数据、复制源读取、设为个人默认和分享链接均要求 `visible`。
- [ ] 标题、发布/取消发布、布局和组件变更要求 `edit`。
- [ ] 删除要求 `delete`，成员管理要求 `manage_permission`。
- [ ] 分享链接不能绕过 dashboard 可见性。

### 文件预览与下载

- [ ] 无 `download` 但能进入业务预览链路的用户可以预览文件，预览请求不执行
  PermissionAction 检查。
- [ ] 同一用户下载原件和打包文件均被拒绝。
- [ ] 授予包含 `download` 的模型后，原件与打包下载立即成功。
- [ ] 撤销后随后的下载立即拒绝；“曾预览”或 `visible` 不产生下载权限。

## 6. 故障、租户和一致性

- [ ] 停止专用测试 OpenFGA 后，进入 ReBAC 的 Check、BatchCheck、List 和写入均明确失败，
  不回退旧四档、Config binding、creator 或数据库细粒度判断。
- [ ] 恢复 OpenFGA 后，不重启业务服务即可恢复；未确认成功的写入不会显示为已生效。
- [ ] 注入 FGA tuple 写入失败，SQL projection ledger 保留可重试失败状态，
  API 返回 `25009`/`19002`，无半成功普通 Grant。
- [ ] 另一租户用户对资源 Check 返回 `19003`，列表不出现该资源，Grant 不能跨租户创建。
- [ ] department/user_group userset 不展开成员；成员变更后权限随集合关系变化。
- [ ] API、Celery Worker、Linsight Worker 对同一资源/动作给出一致结果。
- [ ] 重启任一实例后，自动发现结果未匹配 SQL CURRENT Catalog 时 readiness 失败并拒绝权限流量。

## 7. D0～D6 数据迁移和启服

覆盖 AC-71～147、AC-158。

- [ ] MySQL 与 DM8 仅执行 F048 Alembic revision，确认只发生 DDL，不扫描或改写业务数据。
- [ ] 在维护模式停止 API、Worker、Linsight、Beat、同步任务等全部旧权限读写进程。
- [ ] D0 schema gate 记录 DB revision、Store ID、旧/新 model ID 和进程停写证明。
- [ ] D1 inventory 输出按租户/资源/模型/主体/来源拆分的计数、阻断项和人工项。
- [ ] D2/D3 通过 `src/backend/scripts/migrate_f048_permission_data.py`
  写入并验证规范化控制面和显式新 model tuple。
- [ ] 中断脚本后从 checkpoint 恢复，结果 checksum 相同；第二个脚本实例被 lease 拒绝。
- [ ] 旧模型/binding JSON 非法、未知动作、真实跨租户、循环 parent、无法表达的 manage
  边界等样本均阻断，不静默猜测或扩权。
- [ ] 仅含旧 `view_*` 的合法模型迁为 active 仅可见模型，具体动作全部 DENY；仅缺少对应
  直接 tuple 的孤儿 binding 只记审计、不创建 Grant 且不阻断迁移。
- [ ] D4 门禁满足：blocker=0、人工项签署、受保护 owner 完整、跨租户=0、
  悬空 parent=0、关键动作无未批准扩权。
- [ ] D4 source checksum 在 MySQL/DM8 不同 collation 返回顺序下保持一致；preserved tuple
  核对排除计划退休的 `STALE_RESOURCE_TUPLE` 和 `CANONICAL_IDENTITY_STATE=false` tuple。
- [ ] D4 只激活一个 Catalog release 和一个 authorization model release，
  Store ID 不变。
- [ ] D5 启服后所有进程自动发现同一 Store/latest model，且 heartbeat 与 SQL CURRENT
  Catalog 匹配；不存在 model A/B 运行时路由。
- [ ] D6 在证明目标 tuple/control 完整后才删除已迁移旧 tuple；旧 Config 原始行只读保留
  供排障，但旧 API、模板、运行时解析和 relation 均不可达。
- [ ] 不存在预演、应用级回滚、新→旧转换或旧权限运行时恢复入口。

## 8. BENCH-01

- [ ] 从批准的脱敏生产分布生成正式 fixture，并记录来源审批；不得使用仓库 synthetic
  fixture 判定发布通过。
- [ ] fixture checksum、dataset checksum、authorization model checksum 与批准值一致。
- [ ] 在正式 pinned OpenFGA 上运行 Check、BatchCheck 20/50/100、ListObjects
  direct/department/group/inherit、10/100/1000 结果和业务 cursor + BatchCheck。
- [ ] 报告 P50/P95/P99、错误率、dispatch count、datastore query count 和完整结果 checksum。
- [ ] 所有设计阈值通过；1000 结果场景没有静默截断。
- [ ] 报告明确 `production_derived=true` 和 `release_ready=true`。

## 9. 回归与证据归档

- [ ] Platform 与 Client 页面无 console error，权限按钮隐藏/禁用符合服务端结果。
- [ ] 旧 `/permissions/resources/.../permissions`、`authorize`、relation roster、
  owner transfer 和 Config model/binding 接口返回 404 或不再注册。
- [ ] OpenFGA 日志、业务 request ID、审计日志和 projection ledger 可关联同一变更。
- [ ] 将测试命令、构建版本、环境 pin、数据库、Store、model、Catalog、fixture checksum、
  测试输出和异常修复记录回填 `e2e-test-report.md`。
