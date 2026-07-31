# Feature: F048 ReBAC 权限模型与 Grant 升级

> **本文档定位 — 纯 What（需求与验收合同）**
>
> 本 Spec 只定义做什么、什么结果可验收、迁移与升级必须满足什么门禁，以及明确不做什么。
> 本文档明确规范化关系表的领域边界以及旧数据必须迁往何处；具体字段类型、索引、
> OpenFGA DSL、tuple 形状、API、Service、脚本参数、批次和部署命令属于后续
> [design.md](./design.md) 与 [tasks.md](./tasks.md)，不在本文档重复。

**状态**：✅ Spec、Design ★、Tasks ★ 已确认；功能与迁移脚本开发完成；本地 E2E 经用户确认不执行

**关联 PRD**：[3.0-beta1 ReBAC 逻辑优化](https://dataelem.feishu.cn/wiki/TYmHw4nPzitTQnkUjW8c5NFKnQg)

**优先级**：P0

**所属版本**：v3.0.0-beta1

**依赖**：F004、F006、F007、F008、F027、F036、F040

**版本契约**：[v3.0.0-beta1 release contract](../release-contract.md)

> PRD 的“历史数据迁移和兼容”章节当前为空。本文档第 4 节补齐的是迁移与升级的
> **产品验收合同**；运维执行方案在 Design 阶段补齐。

### PRD 对齐与后续确认覆盖

- PRD 7.6 当前描述为“`can_*` 候选 + 解析关系模型 + 具体能力过滤”；本次讨论已进一步
  确认为：候选可以分阶段获取，但进入资源 ReBAC 后的最终动作结论由 OpenFGA 直接给出，
  Config 或 MySQL 模型不得再充当第二个权限裁决器。
- PRD 中出现的 `manage_members` 业务概念，本 Spec 按当前讨论统一命名为
  `manage_permission`，并采用模型级“是否允许授予同级”策略。
- PRD 4.3 已明确复制资源保留权限模式，`CUSTOM` 副本复制普通白名单；本 Spec 直接纳入，
  不再作为开放问题。
- OQ-01 已确认：`knowledge_space` 与 `knowledge_library` 都是无上级资源的顶级容器，
  固定 `CUSTOM`；二者都可以成为 folder / knowledge_file 的 canonical 直接父级。

---

## 范围边界

### 本次纳入

- 将按资源和目标角色重复的细粒度权限收敛为统一动作目录。
- 为动作配置唯一的 1～4 级，并由等级生成四个累计标准模型。
- 支持自定义模型、模型生效状态，以及模型级 `manage_permission` 同级授权策略。
- 以 PermissionModel 与 PermissionGrant 表达“模型能力”和“资源授权主体集合”。
- 让进入资源 ReBAC 的请求以 OpenFGA 对具体动作的结果作为唯一权限结论。
- 支持用户、部门和既有合法主体类型的多来源授权并集与独立撤销。
- 支持有直接权限父级的资源在 `INHERIT` 与 `CUSTOM` 间切换。
- 将 dashboard 的资源授权、成员管理和具体动作入口一并迁入统一 Grant / Action 语义。
- 权限管理界面展示模式、本级/继承来源、模型、等级和可编辑状态。
- 完成历史动作、模型、绑定、主体来源、父子关系与资源权限模式的一次性升级。
- 将 `permission_relation_models_v1` 与 `permission_relation_model_bindings_v1`
  从 Config 大 JSON 迁入规范化 MySQL/DM8 关系表，并退役其运行时读写。
- 先按既有方式更新镜像并启动服务；旧 model 下进程进入 `MIGRATION_REQUIRED/NOT_READY`
  运维态，不初始化 F048 权限运行时，应用迁移门禁除 `/health` 外统一拒绝 HTTP/WS。随后在
  backend 容器内沿用现有 OpenFGA Store 发布一个新 Authorization Model ID，原地完成 tuple
  转换和旧运行数据退役；校验通过后重启服务，让全部服务只使用新 model 和新业务逻辑并
  自动恢复访问。
- 提供逐项映射、幂等断点续跑、迁移后校验、启服门禁、前向修复和旧路径退役。
- 数据库结构变更只通过 DDL-only Alembic revision 完成；旧权限数据、Config 与 OpenFGA
  tuple 的读取、转换、回填、清理和校验由 `src/backend/scripts/` 下的专用数据迁移脚本完成。

### 本次明确排除

- 不引入显式 DENY、黑名单或“拒绝优先”模型；有效授权仍取白名单并集。
- 不改变组织、部门、用户组自身的管理和成员计算规则。
- 不改变业务 Repository 的租户范围加载职责。
- 不以等级、资源可见性或通用候选集代替具体业务动作鉴权。
- 不建立第二套 `permission_parent` 权限树。
- 不允许直接编辑标准模型的名称、等级或动作集合。
- 不在本 Spec 确定物理字段类型、索引细节、缓存、API、OpenFGA DSL、发布批次或脚本命令。
- 不承诺没有 canonical 权限父级的资源支持继承模式。
- 不为文件预览新增或复用 PermissionAction；预览维持无动作鉴权，只有原件/打包下载入口
  校验 `download`。搜索、RAG 和其他业务行为仍按各自明确动作契约处理。
- 不提供独立 dry-run/迁移预演、旧/新 model 影子裁决、回滚窗口、新→旧数据转换器或旧权限
  运行时恢复路径；迁移或启服验证失败时保持维护并前向修复。
- 不创建、复制或切换 OpenFGA Store，也不同时维护旧、新两个运行 model；旧 model ID
  仅作为 OpenFGA 不可修改/删除的历史版本存在。
- 不在 Alembic revision、应用启动钩子、API 或 Celery 中执行权限数据迁移；服务不会在
  启动时自动回填旧数据。

---

## 1. 核心术语与已确认语义

| 术语 | 规格定义 |
|------|---------|
| PermissionAction | 不编码资源类型和目标角色的统一业务动作；每个动作声明适用资源类型、唯一等级和生效状态 |
| PermissionModel | 一组有效动作及其派生等级；分为标准模型和自定义模型；它是业务权限模型实例，不是权限引擎的模式版本 |
| 标准模型 | 查看者、编辑者、管理者、所有者四个系统模型，分别累计包含 1、1～2、1～3、1～4 级动作 |
| 自定义模型 | 管理员选择有效动作形成的模型；等级由最高动作等级自动得出 |
| PermissionGrant | 某一资源与某一 PermissionModel 的授权集合；其 assignee 可以是用户、部门或既有合法主体 |
| 模型 `active` | 模型是否可被授权以及其既有 Grant 是否能产生权限的总开关；不是业务动作，也不参与等级计算 |
| 资源可见 | 主体至少通过一个有效 Grant 与资源建立关系后，可以看到资源列表项和基础元数据 |
| 具体动作 | 编辑、下载、删除、分享、使用、权限管理等业务行为；必须按该动作本身判定 |
| `INHERIT` | 普通授权沿直接权限父级计算，当前资源不能维护普通本级成员 |
| `CUSTOM` | 当前资源形成权限边界，只使用本级普通 Grant；业务结构父级仍保留 |
| 受保护授权 | 系统创建且不能被普通成员管理接口删除或降级的授权，例如按资源规则确定的所有者 |
| Schema Migration | Alembic revision，只负责 MySQL/DM8 表、列、索引和约束等 DDL，不读取或转换旧业务数据 |
| Permission Data Migration Script | `src/backend/scripts/` 下的一次性运维脚本；在服务已启动、F048 未就绪且 HTTP/WS 迁移门禁生效、schema upgrade 完成后，从 backend 容器内执行旧数据转换、OpenFGA tuple 更新、checkpoint、验证与退役 |

### 1.1 规范示例：同一资源上的直接授权与部门授权

假设知识空间 `100`：

- 自定义模型 `900` 包含 `edit`，用户 `001` 被直接授予模型 `900`；
- 自定义模型 `901` 包含 `download`，用户 `001` 所在部门被授予模型 `901`。

则：

1. 用户 `001` 对资源 `100` 的有效动作是 `edit ∪ download`；
2. 权限界面分别展示“用户直接授权”和“部门授权”两个来源；
3. 撤销用户 `001` 的直接授权后，只删除模型 `900` 的来源；
4. 部门来源仍在，因此 `download` 继续允许，`edit` 在没有其他来源时拒绝；
5. 如果模型 `900` 成功增加 `share`，所有引用模型 `900` 的 Grant 同时获得该动作，不逐资源、逐主体重建授权；
6. 如果模型 `900` 被停用，其全部 Grant 保留用于审计，但不再产生可见性、`edit` 或 `share`。

---

## 2. 用户故事

### US-01 平台权限管理员

作为平台权限管理员，我希望只维护统一动作、动作等级和权限模型，以便减少按资源和目标角色重复配置造成的歧义。

### US-02 资源所有者或权限管理员

作为拥有 `manage_permission` 的资源成员，我希望系统只展示我有权授予的模型，并阻止越级授权，以便安全地维护成员权限。

### US-03 普通资源成员

作为通过用户、部门或其他主体来源获得权限的成员，我希望多个来源自然取并集，撤销其中一个来源时其他合法权限不受影响。

### US-04 自定义模型维护者

作为模型维护者，我希望修改共享模型时能够预览影响，并让所有引用该模型的资源一致生效，而不是触发资源数乘主体数的授权重写。

### US-05 层级资源管理员

作为文件夹或文件的管理员，我希望明确选择继承上级或本级自定义权限，并在界面上看清每个成员从哪里获得权限。

### US-06 升级运维与审计人员

作为升级运维与审计人员，我希望沿用既有“更新镜像并启动、进入 backend 容器执行数据迁移”
的升级方式，在迁移完成后只额外重启一次服务；外部流量在整个过程保持关闭，失败时保持维护
并前向修复，在新逻辑稳定后确认旧路径已退役。

---

## 3. 验收标准

### 3.1 统一动作目录与等级

目标统一动作至少包括：

| 统一动作 | 业务含义 |
|---------|---------|
| `manage_permission` | 管理资源普通授权 |
| `rename` | 修改资源标题或名称 |
| `edit` | 编辑资源内容或设置 |
| `create_folder` | 在容器下创建文件夹 |
| `upload_file` | 向容器上传文件 |
| `move` | 移动资源 |
| `download` | 下载资源 |
| `delete` | 删除资源 |
| `share` | 分享资源 |
| `use` | 使用应用、知识库或工具 |
| `publish` | 发布应用 |
| `unpublish` | 下线应用 |

- **AC-01** — THE SYSTEM SHALL 为每个可配置动作维护唯一的 1、2、3 或 4 级以及适用资源范围。
- **AC-02** — WHEN 新动作尚未分级或已停用, THE SYSTEM SHALL 禁止其进入标准模型、自定义模型和有效授权结果。
- **AC-03** — WHEN 管理员尝试把一个动作同时配置到多个等级, THE SYSTEM SHALL 拒绝保存且保持当前生效版本不变。
- **AC-04** — WHEN 某动作不适用于目标资源类型, THE SYSTEM SHALL 不在模型授权结果中为该资源产生该动作。
- **AC-05** — THE SYSTEM SHALL 不再把 `view_space`、`view_folder`、`view_file`、`view_channel`、`view_app`、`view_kb`、`view_tool` 作为可配置动作展示。
- **AC-06** — WHEN 动作等级成功变化, THE SYSTEM SHALL 按新等级重新得出四个标准模型的累计动作结果，并将影响范围提供给管理员确认和审计。

### 3.2 标准模型、自定义模型与生效状态

- **AC-07** — THE SYSTEM SHALL 固定提供查看者、编辑者、管理者、所有者四个标准模型，其等级分别为 1、2、3、4。
- **AC-08** — THE SYSTEM SHALL 使查看者包含全部 1 级有效动作、编辑者包含 1～2 级、管理者包含 1～3 级、所有者包含 1～4 级。
- **AC-09** — WHEN 用户尝试通过界面或接口修改标准模型名称、等级、动作集合或删除标准模型, THE SYSTEM SHALL 拒绝该请求。
- **AC-10** — WHERE 标准模型包含 `manage_permission`, THE SYSTEM SHALL 允许单独修改该模型“是否允许授予同级”的策略，且不得因此开放其他标准模型字段。
- **AC-11** — WHEN 创建或更新自定义模型, THE SYSTEM SHALL 以其最终所选有效动作的最高等级作为模型等级，在编辑器中实时展示升降级结果，且不接受客户端指定等级。
- **AC-12** — WHEN 自定义模型没有动作、包含未分级动作或包含对其声明范围不合法的动作, THE SYSTEM SHALL 将空动作模型显示为“未定级”并拒绝保存不合法结果。
- **AC-13** — WHEN 自定义模型成功增加或移除动作, THE SYSTEM SHALL 让所有引用该模型的有效 Grant 使用同一新动作结果，不要求重新给每个资源或主体授权。
- **AC-14** — WHEN 模型变更将影响既有 Grant, THE SYSTEM SHALL 在生效前展示受影响的资源数、Grant 数和主体来源数，并要求明确确认。
- **AC-15** — WHILE 模型为 inactive, THE SYSTEM SHALL 禁止新增授权，并使其既有 Grant 不产生资源可见性、具体动作或授权他人的能力。
- **AC-16** — IF 模型更新未完整生效, THEN THE SYSTEM SHALL 继续使用更新前的完整有效状态，不得呈现部分动作已生效的混合结果。
- **AC-17** — WHEN 自定义模型仍被 Grant 引用, THE SYSTEM SHALL 禁止不可恢复的直接删除；管理员可以停用模型，并在引用清零或完成替换后执行最终清理。
- **AC-18** — WHEN 管理员选择“协作编辑”“权限管理”“高级管理”或其他预设创建自定义模型, THE SYSTEM SHALL 只用预设初始化动作选择；最终动作和等级以保存内容为准，预设后续变化不得自动改写已保存模型。

### 3.3 PermissionGrant 与多来源并集

- **AC-19** — THE SYSTEM SHALL 为每个“资源 + PermissionModel”维护唯一的逻辑 Grant，并允许多个主体加入该 Grant。
- **AC-20** — THE SYSTEM SHALL 保留用户直接授权、部门授权、用户组授权及其他已支持主体类型的来源身份，不把它们压平为单一有效结果记录。
- **AC-21** — WHEN 部门或用户组被授权, THE SYSTEM SHALL 保留集合主体语义，不因当时成员名单而展开为全部用户授权。
- **AC-22** — WHEN 同一用户通过多个 Grant 或多个主体来源获得同一资源权限, THE SYSTEM SHALL 对有效动作取并集。
- **AC-23** — WHEN 撤销一个用户直接授权, THE SYSTEM SHALL 只移除该直接来源；该用户通过部门、用户组或其他 Grant 获得的权限继续有效。
- **AC-24** — WHEN 用户退出某部门但仍有直接授权, THE SYSTEM SHALL 仅失去该部门来源的动作，直接授权继续有效。
- **AC-25** — WHEN 完全相同的资源、模型、主体和来源被重复提交, THE SYSTEM SHALL 得到幂等结果，不创建重复的有效授权。
- **AC-26** — WHEN 同一主体对同一资源同时拥有不同模型, THE SYSTEM SHALL 分别保留各模型来源，不以“最高等级模型”覆盖较低等级模型的独有动作或授权策略。
- **AC-27** — WHEN Grant 关联的模型 inactive、缺失或不合法, THE SYSTEM SHALL 使该 Grant fail closed，并将异常暴露给审计和修复流程。

### 3.4 资源可见性与具体动作最终鉴权

- **AC-28** — WHEN 主体通过至少一个 active 模型和有效 Grant 与资源建立关系, THE SYSTEM SHALL 允许其看见该资源的列表项和基础元数据。
- **AC-29** — WHEN 主体没有任何有效 Grant 且没有其他明确的系统级可见关系, THE SYSTEM SHALL 不返回该资源。
- **AC-30** — WHEN 请求通过 C4 明确的系统级身份策略后仍需进入资源 ReBAC，且业务操作需要某一具体动作, THE SYSTEM SHALL 以 OpenFGA 对该动作的结果作为最终权限结论。
- **AC-31** — WHEN 列表候选已经按该列表所要求的具体动作完成权限筛选, THE SYSTEM SHALL 直接使用该结果，不再调用其他数据源做第二次权限裁决。
- **AC-32** — WHEN 候选集只表达通用资源可见性, THE SYSTEM SHALL 不把该候选结果用于证明用户拥有编辑、下载、删除、分享、使用或权限管理等其他动作。
- **AC-33** — WHEN 用户通过某一模型进入资源候选集但该模型不包含目标动作, THE SYSTEM SHALL 对该目标动作返回 DENY。
- **AC-34** — IF 一个需要进入资源 ReBAC 的请求遇到 OpenFGA 不可用、超时或结果不可判定, THEN THE SYSTEM SHALL 返回明确失败，不得改用旧四档关系、Config binding、creator 或数据库细粒度权限产生 ALLOW；既有系统级身份策略必须在请求进入 ReBAC 前明确确定，不能因故障临时启用。
- **AC-35** — WHERE 多租户开启, THE SYSTEM SHALL 只对业务层已限定在当前租户范围内的资源执行权限判定，且不得解析跨租户 Grant。

### 3.5 `manage_permission` 与可授予等级

每个包含 `manage_permission` 的模型独立选择以下策略之一：

| 模型策略 | 该来源模型可授予的目标模型 |
|---------|---------------------------|
| 允许同级 | 目标等级小于或等于来源模型等级 |
| 禁止同级 | 目标等级严格小于来源模型等级 |

本节约束普通资源成员的授权能力。平台超管、租户管理员等系统级身份继续遵守 Constitution C4
的显式身份策略，不作为普通资源成员行展示，也不能在 ReBAC 故障时被临时当作 fallback。

- **AC-36** — WHEN 某来源模型不包含 `manage_permission`, THE SYSTEM SHALL 不让该来源产生新增、修改或删除普通授权的能力，不论其等级多高。
- **AC-37** — WHEN 来源模型包含 `manage_permission` 且允许同级, THE SYSTEM SHALL 允许授予同级及以下模型，拒绝更高级模型。
- **AC-38** — WHEN 来源模型包含 `manage_permission` 且禁止同级, THE SYSTEM SHALL 只允许授予更低级模型。
- **AC-39** — THE SYSTEM SHALL 让每个标准或自定义模型独立维护其同级授权策略，不使用动作级或系统级统一开关覆盖各模型。
- **AC-40** — WHEN 用户通过多个来源模型获得权限管理能力, THE SYSTEM SHALL 对每个来源模型独立计算可授予等级，并对结果取并集。
- **AC-41** — WHEN 一个来源模型有较高等级但没有 `manage_permission`，另一个来源模型有 `manage_permission` 但等级较低, THE SYSTEM SHALL 禁止把前者等级与后者动作、策略拼接成更高授权能力。
- **AC-42** — WHEN 目标模型等级或策略在提交授权期间发生变化, THE SYSTEM SHALL 依据提交时的当前有效模型重新校验，拒绝过期客户端造成的越级授权。
- **AC-43** — WHEN 普通资源成员不具备任何有效 `manage_permission` 来源, THE SYSTEM SHALL 拒绝完整成员名单、新增授权、变更普通成员模型和撤销普通成员请求。
- **AC-44** — WHEN 普通成员管理请求试图删除或降级受保护授权, THE SYSTEM SHALL 拒绝请求；所有者转移如被支持，必须走独立、明确、可审计的业务流程。

### 3.6 权限模式与继承

| 资源类型 | v3.0.0-beta1 权限模式 |
|---------|----------------|
| `knowledge_space` | 固定 `CUSTOM` |
| `folder` | 支持 `INHERIT` / `CUSTOM`；新建默认 `INHERIT` |
| `knowledge_file` | 支持 `INHERIT` / `CUSTOM`；新建默认 `INHERIT` |
| `knowledge_library` | 固定 `CUSTOM`；与 knowledge_space 一样是无上级资源的顶级容器 |
| workflow / assistant / tool / channel / dashboard | 本期固定顶级自定义语义，不提供模式切换 |

- **AC-45** — THE SYSTEM SHALL 复用业务资源既有的直接父级作为权限继承来源，不建立或展示第二套权限父级。
- **AC-46** — WHILE 资源为 `INHERIT`, THE SYSTEM SHALL 通过直接父级获得普通授权，不允许新增、修改或删除普通本级 Grant。
- **AC-47** — WHILE 资源为 `CUSTOM`, THE SYSTEM SHALL 切断普通权限继承并只使用本级普通 Grant，同时允许该本级授权成为其 `INHERIT` 子资源的权限来源；资源的业务结构父级、路径和归属不得改变。
- **AC-48** — WHEN 资源没有合法直接权限父级, THE SYSTEM SHALL 禁止切换为 `INHERIT`。
- **AC-49** — WHEN `INHERIT` 资源移动到新父级, THE SYSTEM SHALL 停止使用旧父级权限并跟随新直接父级。
- **AC-50** — WHEN `CUSTOM` 资源移动到新父级, THE SYSTEM SHALL 保留其本级普通 Grant，不因位置变化自动加入新父级普通授权。
- **AC-51** — WHEN 资源从 `INHERIT` 切换为 `CUSTOM`, THE SYSTEM SHALL 把切换前的有效普通授权快照为本级授权，保留主体类型、模型、部门范围和来源审计，并从此停止跟随父级。
- **AC-52** — WHEN `INHERIT -> CUSTOM` 快照与受保护授权重复, THE SYSTEM SHALL 保留受保护属性且不创建重复的普通授权。
- **AC-53** — WHEN 资源从 `CUSTOM` 切换为 `INHERIT`, THE SYSTEM SHALL 删除本级普通授权、保留受保护授权并开始跟随直接父级。
- **AC-54** — IF 任一权限模式切换未完整成功, THEN THE SYSTEM SHALL 保持切换前的模式和有效权限不变，并向用户报告未发生变更。
- **AC-55** — WHEN `INHERIT` 资源被复制到新位置, THE SYSTEM SHALL 保持副本为 `INHERIT` 并让其继承新位置的直接父级。
- **AC-56** — WHEN `CUSTOM` 资源被复制, THE SYSTEM SHALL 保持副本为 `CUSTOM` 并复制其普通白名单的主体来源、模型引用和范围；受保护授权不得从原资源照搬，必须按新资源的安全规则生成。
- **AC-57** — WHEN 删除或重挂资源会留下无效权限继承关系, THE SYSTEM SHALL 先完成关系清理或拒绝业务操作，不得留下可继续授权的悬空来源。

### 3.7 权限管理界面

- **AC-58** — WHEN 打开资源权限管理界面, THE SYSTEM SHALL 展示当前权限模式以及是否可以切换。
- **AC-59** — WHILE 资源为 `INHERIT`, THE SYSTEM SHALL 展示直接继承来源的资源名称，并把继承成员标记为“继承”且禁止修改、删除。
- **AC-60** — WHILE 资源为 `CUSTOM`, THE SYSTEM SHALL 展示本级普通授权，并只对当前用户可管理的行开放修改或撤销操作。
- **AC-61** — THE SYSTEM SHALL 为成员行展示主体类型、主体名称、模型名称、模型等级、本级/继承来源、直接/部门等来源和受保护状态。
- **AC-62** — WHEN 同一用户通过直接授权和部门授权获得不同模型, THE SYSTEM SHALL 在管理界面保留可解释的来源明细，不只展示一个合并后的最高等级。
- **AC-63** — WHEN 当前用户选择要授予的模型, THE SYSTEM SHALL 只展示至少一个有效来源模型允许其授予的候选模型。
- **AC-64** — WHEN 模型或动作配置被管理员查看, THE SYSTEM SHALL 使标准模型动作集合只读且只展示该等级实际包含的动作，并仅在模型包含 `manage_permission` 时展示同级授权策略。
- **AC-65** — WHEN 用户没有查看完整成员名单的权限, THE SYSTEM SHALL 不返回其他主体和组织信息；如需展示其自身权限，只返回最小化的自身有效动作和来源摘要。

### 3.8 审计、并发与一致性

- **AC-66** — THE SYSTEM SHALL 审计动作等级变化、模型创建/更新/停用、标准模型同级策略变化、Grant 变更、权限模式切换、移动导致的权限来源变化、迁移、启服和旧数据清理。
- **AC-67** — THE SYSTEM SHALL 在审计中记录操作者、租户、目标、变更前后状态、影响范围、结果、时间和失败原因。
- **AC-68** — WHEN 两个管理员基于同一旧版本并发修改模型、Grant 或权限模式, THE SYSTEM SHALL 只接受符合当前版本的更新，并明确拒绝过期覆盖。
- **AC-69** — WHEN 授权或撤销成功返回, THE SYSTEM SHALL 让随后用于安全决策的读取观察到该新状态，不得因旧缓存继续产生与已确认变更相反的 ALLOW。
- **AC-70** — IF 业务数据变更已发生但权限状态未能完成一致更新, THEN THE SYSTEM SHALL 不把该权限变化报告为已生效，并产生可恢复、可审计的异常；业务资源结果继续遵守其 Owner Feature 与 Constitution C4 的失败补偿契约。

### 3.9 PRD 显式交互与新建规则

> AC 编号保持追加而不重排，避免迁移章节既有 AC 的引用失效。

- **AC-148** — WHEN 管理员打开动作等级配置界面, THE SYSTEM SHALL 展示“未分配”以及 1～4 级五个配置区域，并让每个动作只出现在其中一个区域。
- **AC-149** — WHEN 新动作首次登记, THE SYSTEM SHALL 默认把它放入“未分配”；在管理员完成 1～4 级配置前，该动作不得出现在模型编辑器、标准模型或正式授权条件中。
- **AC-150** — WHEN 新建知识空间, THE SYSTEM SHALL 将其初始化为 `CUSTOM`，并按现有安全规则生成受保护所有者授权。
- **AC-151** — WHEN 在合法直接父级下新建文件夹或文件, THE SYSTEM SHALL 将其初始化为 `INHERIT`，同时按现有安全规则生成可展示但不破坏普通继承语义的受保护所有者授权。
- **AC-152** — WHEN 用户请求在 `INHERIT` 与 `CUSTOM` 之间切换, THE SYSTEM SHALL 在变更前展示成员复制或本级授权删除等影响并要求确认；用户取消时模式和权限不得变化。
- **AC-153** — THE SYSTEM SHALL 将 dashboard 纳入本期统一 PermissionGrant、成员管理和动作迁移；列表/详情/组件数据查询/复制源读取/设为个人默认使用固定资源可见性，分享链接不得绕过该可见性；标题、状态（含发布/取消发布）、布局和组件变更检查 `edit`，删除检查 `delete`，授权成员检查 `manage_permission`，新建 dashboard 继续由既有菜单能力控制。
- **AC-154** — WHEN 用户预览文件, THE SYSTEM SHALL 不执行 PermissionAction 鉴权；WHEN 用户下载原件或打包文件, THE SYSTEM SHALL 检查 `download`，不得把“预览过”或资源可见性当作下载授权。
- **AC-155** — THE SYSTEM SHALL 让业务资源 Service 负责资源存在性、所属租户、状态、父级和其他业务规则，并把已验证的资源标识/上下文传给权限服务；权限领域不得查询或裁决这些业务数据，只负责与业务无关的授权计算和权限事实投影。
- **AC-156** — WHEN 任一动作的等级、生效状态或适用范围变化, THE SYSTEM SHALL 在同一完整 Catalog release 中重新计算四个标准模型的累计动作集合、所有自定义模型的派生等级和所有模型的有效资源动作，不得只更新被直接编辑的模型。
- **AC-157** — THE SYSTEM SHALL 允许一个资源同时存在多个 owner；创建者对应一个受保护 owner，
  其他直接 owner 作为独立普通来源保留。WHEN F048 启用新权限逻辑, THE SYSTEM SHALL
  退役既有 F018 owner 交接 API，且本期不提供受保护 owner 转让能力；普通 owner 的独立
  增删仍按既有成员管理合同执行，不得删除创建者受保护来源。
- **AC-158** — THE SYSTEM SHALL 让 Alembic revision 只执行 MySQL/DM8 数据库结构 DDL；
  旧权限数据、Config 和 OpenFGA tuple 的读取、转换、回填、去重、清理、checkpoint 与验证
  必须由运维人员在已启动但 F048 未就绪的 backend 容器内，通过 `src/backend/scripts/`
  下的专用数据迁移脚本显式执行，不得由 revision、API、Celery 或应用启动钩子自动执行。

---

## 4. 数据迁移与升级验收方案

### 4.1 总体原则

本次升级从 v2.5/v2.6 的四档静态关系、Config 中的 relation model/binding、
既有 OpenFGA tuple 和资源父子关系迁移到本 Spec。升级必须遵守：

1. 更新镜像并启动 API、Celery、Linsight 等进程；当 OpenFGA 最新 model 仍是旧版本时，
   进程必须存活但处于 `MIGRATION_REQUIRED/NOT_READY`，不得初始化 F048 权限运行时或
   发布 ready heartbeat；API 的 HTTP/WS 迁移门禁除 `/health` 外统一拒绝访问，Celery/
   Linsight 暂停消费任务；
2. 由正常启动链完成 Alembic MySQL/DM8 schema DDL，再由运维人员进入 backend 容器，通过
   `src/backend/scripts/`
   专用脚本执行唯一一次正式权限数据迁移；两者不得互相 import 或混合职责；
3. OpenFGA Store ID 保持不变；仍合法的 system/组织/shared/parent tuple 原地复用，新授权
   tuple 原地写入并在核对后删除已迁移资源的旧四档/废弃 relation tuple；
4. 数据迁移脚本校验通过后重启 API、Celery、Linsight 等服务；重启后的全部权限读写只启用
   新 model ID，不保留双 model client、运行时双写或 fallback；readiness 通过后迁移门禁
   自动解除；
5. 未映射、跨租户、孤儿、冲突和语义可能扩权的数据 fail closed；
6. 数据迁移脚本可重复执行、可断点续跑、可审计，但不提供独立 dry-run 或生产迁移预演；
7. 数据迁移或启服验证失败时保持维护并在新 model 上前向修复，不恢复旧应用与旧权限运行时。

### 4.2 初始动作映射基线

下表是本 Spec 的建议迁移基线。正式迁移前必须由产品、后端、安全和测试共同确认最终等级；
未经确认不得进入生产切换。

| 旧动作族 | 新动作 | 建议初始等级 | 迁移要求 |
|---------|--------|-------------:|---------|
| `view_*` | 不再作为动作 | — | 模型仍有其他动作时由 Grant 自然保留可见性；仅含 `view_*` 的旧自定义模型按 AC-79 人工处理，不得自动赋予正文、下载或其他具体动作 |
| `manage_*` | `manage_permission` | 3 | 根据原模型可管理目标范围推导模型级同级策略；不能由新等级规则无损表达的记录进入人工清单，不得自动扩权 |
| `rename_folder` / `rename_file` | `rename` | 2 | 保留适用资源范围 |
| `edit_*` | `edit` | 2 | 按目标资源适用范围迁移 |
| `AccessType.DASHBOARD_WRITE` | `edit` | 2 | dashboard 标题、状态、布局和组件更新；旧删除入口改为独立 `delete` |
| `create_folder` | `create_folder` | 2 | 作为目标容器动作 |
| `upload_file` | `upload_file` | 2 | 作为目标容器动作 |
| `move_folder` / `move_file` | `move` | 2 | 保留源资源与目标容器的业务校验要求 |
| `download_folder` / `download_file` | `download` | 1 | 不扩大文件夹递归下载范围 |
| `delete_*` | `delete` | 4 | 保留各资源删除约束 |
| `share_*` | `share` | 3 | 按适用资源范围迁移 |
| `use_app` / `use_kb` / `use_tool` | `use` | 1 | 不等同于编辑 |
| `publish_app` | `publish` | 3 | 仅适用于应用 |
| `unpublish_app` | `unpublish` | 3 | 仅适用于应用 |
| `AccessType.DASHBOARD` | 固定资源可见性 | — | dashboard 列表、详情、数据查询和复制源读取；不新增可配置 `view_dashboard` |

### 4.3 正式迁移的源校验与逐项映射

- **AC-71** — WHEN Alembic schema upgrade 已成功且全部权限读写进程停止, THE SYSTEM SHALL
  由 `src/backend/scripts/` 专用脚本启动唯一正式 data migration run，先校验 schema、源环境、
  迁移锁和旧数据完整性，再直接写入规范化关系表与现有 Store；不要求先执行独立 dry-run。
- **AC-72** — THE SYSTEM SHALL 在数据迁移脚本的源校验阶段盘点旧动作、四档关系、自定义模型、
  Config binding、资源授权 tuple、直接/部门/用户组来源、受保护所有者、资源父级和异常记录。
- **AC-73** — THE SYSTEM SHALL 输出旧动作到新动作、旧系统/自定义模型到新模型、旧授权到目标 Grant、资源到目标权限模式的可追溯映射。
- **AC-74** — THE SYSTEM SHALL 分别统计已创建、复用、跳过、删除、去重和人工处理的数据量，并按租户、资源类型、模型、主体类型和来源拆分。
- **AC-75** — WHEN 发现跨租户关系、不存在的资源/主体/模型、无效父级、循环父级、非法动作、空自定义模型或不能表达的 `manage_*` 范围, THE SYSTEM SHALL 将其列入阻断或人工处置清单，不得静默放行。
- **AC-76** — IF 源校验或目标写入存在未关闭阻断项, THEN THE SYSTEM SHALL 停止后续批次并
  保持服务关闭；修复后只能基于 checkpoint 幂等续跑并重新校验，不得绕过阻断项启服。

### 4.4 模型、Grant 与主体来源迁移

- **AC-77** — WHEN 普通资源的旧 viewer/editor/manager/owner 直接 tuple 没有匹配的自定义 binding, THE SYSTEM SHALL 分别映射到四个标准模型，保持原授权主体、资源范围和受保护属性；有 binding 时按 AC-118 使用其模型。平台超管、租户管理员等显式系统级身份不得被转换为普通 Grant，并继续遵守 Constitution C4。
- **AC-78** — WHEN 迁移旧自定义模型, THE SYSTEM SHALL 按已确认的动作映射生成自定义模型，依据最高有效动作计算等级，保留原生效/停用状态和可追溯的旧模型标识。
- **AC-79** — WHEN 旧自定义模型在移除 `view_*` 后没有任何有效动作, THE SYSTEM SHALL 禁止自动映射到可能扩权的标准模型，将其列入切换阻断清单，并要求管理员选择一个具有真实动作的目标模型；在完成选择前不得静默扩权或以空自定义模型进入生产。
- **AC-80** — WHEN 旧模型包含任一 `manage_*`, THE SYSTEM SHALL 只在其目标范围能由新等级规则表达时自动迁移 `manage_permission` 与同级策略；非单调或可能扩权的范围必须人工确认。
- **AC-81** — THE SYSTEM SHALL 把同一资源与同一新模型的授权主体归入同一逻辑 Grant，不为每个主体复制模型动作。
- **AC-82** — THE SYSTEM SHALL 保留直接用户、部门、用户组和其他合法主体来源，并保留“包含子部门”等既有主体范围；部门或用户组不得按迁移时成员名单展开为用户。
- **AC-83** — WHEN 同一用户因直接授权和部门授权同时有效, THE SYSTEM SHALL 保留两条独立来源；不得只迁移合并后的最高模型。
- **AC-84** — WHEN 完全相同的旧授权被重复记录, THE SYSTEM SHALL 只对相同资源、模型、主体和来源做幂等去重；不同来源不得互相去重。
- **AC-85** — WHEN 旧模型或绑定无法安全映射, THE SYSTEM SHALL 不让其在新系统产生 ALLOW，并在切换门禁中要求人工关闭。

### 4.5 权限模式与父级迁移

- **AC-86** — THE SYSTEM SHALL 保留资源既有业务结构父级，并使用同一直接父级表达权限继承，不创建 `permission_parent`。
- **AC-87** — WHEN 迁移 `knowledge_space` 或没有 canonical 权限父级的顶级资源, THE SYSTEM SHALL 将其设为 `CUSTOM`。
- **AC-88** — WHEN 文件夹或文件除受保护授权外没有普通本级授权, THE SYSTEM SHALL 将其迁为 `INHERIT` 并继续跟随直接父级。
- **AC-89** — WHEN 文件夹或文件存在普通本级授权, THE SYSTEM SHALL 将其迁为 `CUSTOM`，并快照迁移前的有效普通授权集合，避免从旧“父级与本级叠加”语义切换后静默丢权。
- **AC-90** — WHEN 快照包含同一主体的多个不同来源或不同模型, THE SYSTEM SHALL 分别保留；只有完全相同的授权来源才可去重。
- **AC-91** — WHEN 迁移 `knowledge_library`, THE SYSTEM SHALL 将其作为无上级资源的顶级容器固定为 `CUSTOM`，不得创建 parent 或开放 `INHERIT` 切换。
- **AC-92** — WHEN 资源父级缺失、跨租户或形成循环, THE SYSTEM SHALL 阻止该资源进入 `INHERIT`，并纳入人工修复清单。

### 4.6 正式迁移、语义校验与切换门禁

- **AC-93** — WHEN 正式数据迁移脚本被重复执行或从中断点恢复, THE SYSTEM SHALL 得到相同目标结果，不重复授权、不丢失已成功批次。
- **AC-94** — WHEN 同一环境已有数据迁移脚本运行, THE SYSTEM SHALL 阻止第二个脚本进程并发修改同一迁移范围。
- **AC-95** — IF 正式迁移发生错误, THEN THE SYSTEM SHALL 停止后续批次、保留可诊断状态，
  保持服务关闭，并允许在修复后从已验证 checkpoint 安全续跑。
- **AC-96** — THE SYSTEM SHALL 在启服前完成全量来源计数与目标计数核对，并对所有高风险动作、受保护所有者、模式边界及直接/部门并集场景执行新模型语义校验。
- **AC-97** — WHEN 新语义有意改变旧结果, THE SYSTEM SHALL 把每类预期扩权或撤权列入经批准的差异清单；清单外差异必须阻断切换。
- **AC-98** — THE SYSTEM SHALL 在切换门禁中要求：阻断级异常为零、人工项已签署、跨租户关系为零、悬空父级为零、受保护授权完整、关键动作无未批准扩权。
- **AC-99** — WHEN 正式迁移窗口开始, THE SYSTEM SHALL 停止全部旧授权读写进程并阻止任何
  未经迁移 run 记录的增量，直到新服务通过启服门禁。
- **AC-100** — WHEN 启服门禁通过, THE SYSTEM SHALL 保持现有 Store ID 不变，同时让 API、
  后台任务、同步任务和全部应用实例只使用新 Authorization Model 与新 Grant 语义；
  不得保留旧 binding 写入入口或 dual/legacy model client。
- **AC-101** — IF 启服后安全验证失败, THEN THE SYSTEM SHALL 重新进入维护、停止权限写入并
  在新 model 与新控制面上前向修复；不得恢复旧 model、回放旧 Config、逐请求 fallback 或静默放行。

### 4.7 启服后监控、前向修复与启服前旧路径退役

- **AC-102** — THE SYSTEM SHALL 在启服后持续报告具体动作拒绝/允许异常、Grant/模型异常、
  权限模式异常、跨租户风险、迁移人工项和前向修复状态。
- **AC-103** — THE SYSTEM SHALL 不提供 F048 应用级回滚窗口、新→旧数据转换或旧权限运行时
  恢复能力；旧 model ID 仅是 OpenFGA 不可删除的历史记录，旧 Config 不得保留为运行时来源。
- **AC-104** — WHEN D3 已证明对应新关系和规范化控制面完整, THE SYSTEM SHALL 在 D4 启服
  门禁前退役旧动作模板、旧 Config binding/model 运行数据、旧授权写入口、兼容 alias 和
  旧 ALLOW fallback；不得留到启服后再清理。
- **AC-105** — WHEN 正式数据迁移脚本退役旧运行数据, THE SYSTEM SHALL 先证明所有有效
  模型、Grant、主体来源、受保护授权和父级均已迁移，并把来源快照、目标 checksum 与删除
  fingerprint 持久化到迁移审计记录；不得依赖保留旧运行数据来核对。
- **AC-106** — THE SYSTEM SHALL 在 MySQL 与 DM8 支持的部署中提供相同的 Alembic DDL、
  数据迁移脚本结果和切换门禁。
- **AC-107** — IF 启服后需要修复授权、撤权、模型或权限模式数据, THEN THE SYSTEM SHALL
  通过新控制面和 durable projection operation 执行可审计的前向修复；不得重新启用旧 model、
  恢复旧 Config 或丢失已向用户报告成功的权限变化。

### 4.8 Authorization Model、旧模型与 Config JSON 专项迁移

本节是第 4.1～4.7 节的专项细化，明确回答三类数据如何迁移：

1. OpenFGA Authorization Model 在同一 Store 从旧 model ID 单向切换到新 model ID；
2. 旧 `owner/manager/editor/viewer`、标准模型和自定义模型如何映射；
3. 两份 Config 大 JSON 如何迁入规范化关系表。

#### 4.8.1 旧 Authorization Model → 新 Authorization Model

当前旧版本为仓库中的 `v2.0.2` 静态模型：资源类型直接使用
`owner/manager/editor/viewer`，再计算 `can_manage/can_edit/can_read/can_delete`。
新版本引入 PermissionModel、PermissionGrant 和具体动作关系，同时继续保留
`system`、`tenant`、`department`、`user_group`、必要的 `shared_with` 以及层级资源
`parent` 等仍有效的系统关系。

OpenFGA Authorization Model 不可原地修改；每次发布都会产生新的 model ID。
因此本次采用“启动新镜像并自动拒绝业务访问、容器内同 Store 原地迁移、重启后只启用新 model”
的单向迁移方式：

| 阶段 | 服务状态 | 迁移行为 |
|------|-----------------|---------|
| D0 启动新镜像并自动阻断访问 | 进程存活、F048 不就绪 | 更新镜像并正常启动 API、Celery、Linsight；旧 model 只允许进程进入 `MIGRATION_REQUIRED/NOT_READY`，不初始化 F048 权限运行时、不发布 ready heartbeat；HTTP/WS 迁移门禁除 `/health` 外统一拒绝，Celery/Linsight 暂停消费任务；记录现有 Store、旧 model ID 与源数据 watermark |
| D1 Schema Migration | 进程存活、F048 不就绪 | 正常启动链中的 Alembic revision 只执行 MySQL/DM8 DDL并验证单 head；不创建 data migration run，不读写旧数据或 OpenFGA |
| D2 Data Migration Script | backend 容器可进入、访问门禁生效 | 运维进入 backend 容器，从 `src/backend/` 运行专用脚本；脚本创建正式 run，在现有 Store 发布新 model，并校验/导入动作、模型、binding、Grant、assignee 和 mode |
| D3 脚本转换并退役旧数据 | 访问门禁生效、F048 不就绪 | 同一脚本原地复用仍合法的组织/共享/parent/system tuple；写入新 Catalog/Grant/mode tuple，逐批核对后删除旧四档/废弃 tuple 和旧 Config 运行数据 |
| D4 脚本校验 | 访问门禁生效、尚未重启 | 专用脚本 verify 核对来源/目标计数、checksum、人工项和新模型高风险动作；已迁移类型旧 tuple/Config 计数必须为零 |
| D5 重启并自动发现 | 重启 → 新 model | 迁移成功后重启 API、Celery、Linsight 等进程；配置只保留连接信息与稳定 Store name；全部实例发现唯一同名 Store 的最新 model，并要求它与 SQL CURRENT Catalog 引用的 ACTIVE release 一致；dual/legacy model 关闭；readiness、heartbeat 与 smoke 100% 后迁移门禁自动解除 |
| D6 前向运行 | 新 model | 异常只做前向修复；旧 model ID 仅作为 OpenFGA 不可删除的历史版本存在 |

- **AC-108** — WHEN 正式数据迁移脚本开始, THE SYSTEM SHALL 证明 Alembic schema upgrade
  已成功、API HTTP/WS 迁移门禁已生效且 ready F048 runtime heartbeat 为零。API、Celery、
  Linsight 进程可以存活，但旧 model 下必须处于 `MIGRATION_REQUIRED/NOT_READY`，不得初始化
  F048 权限运行时；任一实例仍 ready、业务访问未被拒绝或后台任务仍被消费时必须阻断迁移。
- **AC-109** — WHEN 发布新 Authorization Model, THE SYSTEM SHALL 在现有 Store 中记录新的
  不可变 model ID，不得覆盖、伪装或复用旧 model ID，也不得创建或切换 Store。
- **AC-110** — WHILE 迁移和启服门禁尚未完成, THE SYSTEM SHALL 不处理生产授权请求；
  同一 Store 只由专用数据迁移脚本写入、删除和校验。应用进程可以为进入容器和执行运维而
  保持启动，但不得因新 model 已发布而动态切换为 ready；必须等待迁移验证成功后统一重启。
- **AC-111** — WHEN 向现有 Store 写入新类型或关系 tuple, THE SYSTEM SHALL 显式指定新
  model ID 作为校验上下文；仍合法的基础 tuple 必须原地复用，不得复制到另一 Store。
- **AC-112** — THE SYSTEM SHALL 通过“旧 tuple 转换为新 tuple”完成迁移，不得把形状相同的一份 tuple 同时写给旧/新 model 作为迁移方案；现有同 tuple shadow-write 机制不能替代本次模型转换。
- **AC-113** — WHILE D0～D5 运行, THE SYSTEM SHALL 保持旧授权、模型、binding、父级和资源
  模式写入冻结；迁移前启动的进程不得初始化 F048 权限运行时或发布 ready heartbeat；
  任何迁移 watermark 之后的未记录变化必须阻断启服。
- **AC-114** — WHEN 执行迁移后语义校验, THE SYSTEM SHALL 使用经过批准的旧动作到新动作
  映射验证直接授权、继承、多来源并集和具体动作，不得仅比较 tuple 数量，也不得运行线上
  旧/新 model shadow 裁决。
- **AC-115** — WHEN D5 启服成功, THE SYSTEM SHALL 让 API、后台任务、同步任务和全部应用
  实例按稳定 Store name 发现同一 Store 的最新新 model，并要求其 Store/model/checksum 与
  SQL CURRENT Catalog 引用的唯一 ACTIVE release 一致；每个 Check/List/Write 显式发送该
  model ID，同时停止产生旧资源四档 tuple 与 Config binding。
- **AC-116** — THE SYSTEM SHALL 不提供从新 model 恢复到旧 model 的应用级迁移路径；
  IF D5 后发现问题, THEN THE SYSTEM SHALL 重新维护并在新 model 上前向修复。
- **AC-117** — WHEN D4 通过, THE SYSTEM SHALL 证明已迁移资源的旧四档/废弃 relation tuple
  与旧 Config 运行数据已经删除；旧 model ID 因 OpenFGA 不可变而保留时，也不得出现在
  runtime 配置、client、heartbeat 或 readiness 中；Store/model/Catalog ID 不要求写入配置。

#### 4.8.2 旧 OpenFGA 关系迁移

迁移只转换 OpenFGA 中真实存在的直接 tuple；`can_*`、四档包含关系以及父级继承计算出的
有效用户集合不是持久化授权事实，禁止展开迁移。

| 旧关系事实 | 新方案 |
|-----------|--------|
| 业务表/成员事实确认的受保护创建者 | 进入“资源 + 新所有者标准模型”的 Grant，并标记为受保护 assignee；缺少直接 tuple 但事实唯一时审计修复 |
| 其他资源直接 `owner` | 有唯一匹配 binding 时使用其迁移后模型，否则进入新所有者标准模型 Grant |
| 资源直接 `manager` | 进入“资源 + 新管理者标准模型”的 Grant；保留原 userset 主体 |
| 资源直接 `editor` | 进入“资源 + 新编辑者标准模型”的 Grant；保留原 userset 主体 |
| 资源直接 `viewer` | 进入“资源 + 新查看者标准模型”的 Grant；保留原 userset 主体 |
| 有匹配 binding 的四档 tuple | 不按四档默认模型迁移，改用 binding 指向的已迁移 PermissionModel |
| `can_read/can_edit/can_manage/can_delete` | 计算关系，不存在可迁移的直接 tuple |
| 层级资源 `parent` | `INHERIT` 保留；`CUSTOM` 不参与权限继承，但业务结构父级继续存于业务表 |
| `shared_with` / tenant share | 继续作为系统可见关系，不转换为普通成员 Grant |
| `system` / `tenant` / `department` / `user_group` 基础关系 | 保留其既有领域语义，不转换为普通资源 Grant |

- **AC-118** — WHEN 读取非受保护的旧 `owner/manager/editor/viewer` tuple, THE SYSTEM SHALL 先按资源、主体、relation 和范围查找唯一匹配的旧 binding；有 binding 时使用其 model_id，无 binding 时才映射到对应标准模型。
- **AC-119** — THE SYSTEM SHALL 只为直接 tuple 创建 Grant assignee，不得把 owner 蕴含 manager/editor/viewer、manager 蕴含 editor/viewer 或 `parent` 继承得到的用户物化为新 assignee。
- **AC-120** — WHEN 迁移资源创建者或其他受保护 owner, THE SYSTEM SHALL 结合资源业务表和既有成员事实识别它，并映射到所有者标准模型的受保护 assignee；仅凭 relation 名称不能推断所有 owner 都受保护。IF canonical 事实唯一但缺少直接 owner tuple, THEN THE SYSTEM SHALL 补建受保护来源并记录修复；IF 存在多个 CREATOR、主体冲突或冲突 binding, THEN THE SYSTEM SHALL 阻断迁移。knowledge_space/channel 的唯一 CREATOR 与 `user_id` 因既有 F018 不一致时，迁移须保留 CREATOR 为 protected、差异 `user_id` 为 ordinary 并登记差异，不得静默删除任一当前有效 owner 来源。
- **AC-121** — WHEN 旧主体为 `department:{id}#member`、`user_group:{id}#member` 或 `user_group:{id}#admin`, THE SYSTEM SHALL 原样保留主体类型与 userset 语义，不展开为用户。
- **AC-122** — WHEN 旧部门 binding 标记 `include_children=true`, THE SYSTEM SHALL 以 binding 中的根部门和范围作为唯一业务授权来源；历史上为子部门展开出的多个 tuple 不得被误迁为多个独立授权。
- **AC-123** — WHEN 旧 tuple 找不到资源、主体或合法租户，或者一个 tuple 匹配多个互相冲突的 binding, THE SYSTEM SHALL 将其列为阻断项，不得猜测目标模型。
- **AC-124** — WHEN binding 存在但对应直接 tuple 不存在, THE SYSTEM SHALL 把它标记为孤儿 binding，不创建有效 Grant。
- **AC-125** — WHEN 迁移 `parent` 关系, THE SYSTEM SHALL 根据目标 ResourcePermissionMode 决定其是否参与权限继承，不得复制出第二套 `permission_parent`。
- **AC-126** — WHEN 迁移 `shared_with`、系统管理员、租户成员、部门成员或用户组成员关系, THE SYSTEM SHALL 保持其原系统用途，不得因为其能产生可见性而把它伪装成普通 PermissionGrant。

#### 4.8.3 旧标准模型与自定义模型迁移

当前 `permission_relation_models_v1` 中每个模型包含：

`id`、`name`、`relation`、`grant_tier`、`permissions`、
`permissions_explicit`、`is_system`。

迁移规则如下：

| 旧模型形态 | 新模型处理 |
|-----------|-----------|
| 四个默认系统模型，`permissions_explicit=false` | 分别映射到固定 ID 的查看者、编辑者、管理者、所有者；新动作集合只由动作等级累计生成 |
| 系统模型被编辑且 `permissions_explicit=true`，映射后与新标准模型完全一致 | 仍映射到对应新标准模型；可无损表达的旧 `manage_*` 范围迁入该标准模型的同级策略 |
| 系统模型被编辑且映射后与新标准模型不一致 | 生成带历史来源标记的自定义模型快照；仅原 binding 指向该快照，不能把新标准模型改成旧动作集合 |
| 普通自定义模型 | 保留稳定 ID 与名称；旧动作逐项映射、去重，等级由最高新动作等级重新计算 |
| 自定义模型仅剩 `view_*` | 不自动映射；进入人工选择目标模型的切换阻断清单 |
| 自定义模型包含 `manage_*` | 映射为 `manage_permission`；根据旧目标档位与新模型等级推导同级策略，不能无损表达时人工确认 |

旧 `relation` 与 `grant_tier` 只作为迁移线索和审计信息，不能继续充当新模型等级或可授权范围；
新模型等级与策略必须按新规则重新得出。

- **AC-127** — WHEN 初始化四个新标准模型, THE SYSTEM SHALL 使用固定模型身份、固定等级和当前有效动作等级的累计结果；不得把旧 Config 中的 `permissions` 数组继续作为标准模型运行时动作集合。
- **AC-128** — WHEN 旧系统模型从未显式编辑, THE SYSTEM SHALL 将引用它的 binding 映射到对应新标准模型。
- **AC-129** — WHEN 旧系统模型被显式编辑且映射动作与新标准模型不同, THE SYSTEM SHALL 创建带历史来源标记的自定义模型快照并重定向原 binding；新标准模型仍保持不可直接编辑，该快照后续按普通自定义模型规则管理。
- **AC-130** — WHEN 旧系统模型的显式动作经映射后与新标准模型完全一致, THE SYSTEM SHALL 直接使用新标准模型，不创建无意义的历史快照，并按 AC-134～AC-135 迁移或阻断其同级授权策略。
- **AC-131** — WHEN 迁移普通自定义模型, THE SYSTEM SHALL 保留其稳定 ID、名称和配置范围，把每个旧 permission ID 映射到零个或一个统一动作并去重，再由最高动作等级派生新等级。
- **AC-132** — WHEN 旧自定义模型没有 active 字段且其数据合法, THE SYSTEM SHALL 以 active 状态导入；已被明确停用、删除或判定非法的模型不得因缺省值重新生效。
- **AC-133** — WHEN 旧自定义模型引用未知 permission ID、不适用于任何目标资源或映射后为空, THE SYSTEM SHALL 阻断自动生效并进入人工清单。
- **AC-134** — WHEN 旧 `manage_*` 目标集合恰好对应“低于新模型等级的全部模型”或“同级及以下全部模型”, THE SYSTEM SHALL 分别迁为“禁止同级”或“允许同级”。
- **AC-135** — WHEN 旧 `manage_*` 目标集合包含更高级模型、缺少中间低级模型或不能形成连续等级边界, THE SYSTEM SHALL 禁止自动推导 `manage_permission` 策略并要求人工确认，不能取更宽权限近似。
- **AC-136** — WHEN 一个旧自定义模型被多个资源和主体引用, THE SYSTEM SHALL 只创建一个新 PermissionModel，并让所有目标 Grant 引用它；不得按资源或主体复制模型定义。

#### 4.8.4 Config 大 JSON → 规范化关系表

以下是本期必须具备的规范化关系表合同。物理字段类型、索引名和 ORM 类名在 Design 中确定，
但不得把动作数组、模型数组、绑定数组继续塞入单行 JSON：

| 关系表合同名 | 承载事实 | 主要迁移来源 |
|-------------|---------|-------------|
| `permission_action` | 动作代码、等级、状态 | 统一动作目录与第 4.2 节映射 |
| `permission_action_resource_scope` | 动作适用的资源类型 | 现有各资源 permission template |
| `permission_model` | 标准/自定义类型、名称、派生等级、active、同级策略、显式配置范围 | `permission_relation_models_v1` |
| `permission_model_action` | 一个模型包含哪些动作 | 模型 `permissions[]` 经统一动作映射后的结果 |
| `permission_grant` | 租户内“资源 + PermissionModel”的唯一逻辑 Grant | OpenFGA 直接四档 tuple 与 binding |
| `permission_grant_assignee` | Grant 的主体、userset、include_children、直接/部门等来源、受保护属性 | binding 与匹配的直接 tuple |
| `resource_permission_mode` | 资源的 `INHERIT` / `CUSTOM` 模式与版本 | 资源父级、普通本级授权和第 4.5 节规则 |
| `authorization_model_release` | 同一 OpenFGA Store 中的新 model ID、发布状态与启服结果 | OpenFGA 单向迁移过程 |
| `permission_migration_run` | 专用数据迁移脚本的正式 run、checkpoint、差异、人工项与结果 | 本次 scripts 数据迁移过程；不是 Alembic 状态 |
| `permission_migration_item` | 每条旧模型、binding、tuple 的来源定位、目标记录、状态和差异 | scripts 数据迁移逐项映射与断点恢复 |

MySQL/DM8 关系表是权限配置、模型定义和绑定关系的控制面真相；OpenFGA 是由这些事实发布出的
执行面。数据库记录不得在 OpenFGA 拒绝或不可用时充当第二个 ALLOW 裁决器。

- **AC-137** — THE SYSTEM SHALL 把 `permission_relation_models_v1` 中每个合法模型迁为一条 `permission_model` 记录，并把其动作拆为多条 `permission_model_action` 记录。
- **AC-138** — THE SYSTEM SHALL 把 `permission_relation_model_bindings_v1` 中每个合法 binding 迁为对应 `permission_grant` 与 `permission_grant_assignee`，多个相同“资源 + 模型”binding 共享一个 Grant。
- **AC-139** — THE SYSTEM SHALL 为动作适用资源范围建立规范化关联，不得在 `permission_action` 或 `permission_model` 中使用大 JSON 保存资源类型数组或动作数组。
- **AC-140** — THE SYSTEM SHALL 为 Grant assignee 保留主体类型、主体 ID、userset relation、include_children、来源和受保护属性；旧 binding 的拼接 `key` 仅用于迁移核对，不作为新系统主键或业务真相。
- **AC-141** — WHEN 从不带 tenant_id 的旧 Config binding 迁移, THE SYSTEM SHALL 从 canonical 业务资源解析 tenant_id 并验证主体范围；无法唯一解析、跨租户或资源不存在的 binding 必须阻断。
- **AC-142** — WHEN `permission_relation_models_v1` 或 `permission_relation_model_bindings_v1` JSON 无法解析、字段缺失、ID 重复、引用不存在模型或 binding relation 与模型 relation 冲突, THE SYSTEM SHALL 报告原始记录定位并阻断相关数据迁移，不得像旧运行时一样静默回退默认值或空数组。
- **AC-143** — WHEN SQL 控制面变更需要发布到 OpenFGA, THE SYSTEM SHALL 保留可审计的发布状态并确保失败可重试、可对账；SQL 记录存在但 OpenFGA 未生效时不得报告权限已生效。
- **AC-144** — WHEN 新系统完成启服, THE SYSTEM SHALL 停止读取和写入
  `permission_relation_models_v1` 与 `permission_relation_model_bindings_v1`；两份 Config
  若暂时保留，只能作为只读迁移审计来源。
- **AC-145** — WHEN 源/目标计数、引用和权限语义核对通过且旧数据无运行时引用,
  THE SYSTEM SHALL 删除两份 Config 大 JSON 及其专用缓存、解析、全量读改写和第二 PDP 路径。
- **AC-146** — THE SYSTEM SHALL 使上述规范化表、唯一性约束和迁移结果同时兼容 MySQL 与 DM8；不得使用仅 MySQL 可运行的 JSON 查询或方言特性。
- **AC-147** — THE SYSTEM SHALL 以 `permission_migration_item` 逐条保存旧记录到新记录的映射、处理状态和失败原因，使断点恢复与审计不依赖另一份大 JSON 迁移报告。

---

## 5. 边界情况

| ID | 场景 | 预期结果 |
|----|------|---------|
| EC-01 | 模型动作变更期间有并发授权 | 过期请求被版本冲突拒绝；不得按旧等级越权授权 |
| EC-02 | 用户同时通过直接、部门、用户组获得相同模型 | 权限只计算一次语义结果，但来源分别保留；撤销任一来源不影响其余来源 |
| EC-03 | 用户的多个模型有相同等级但动作不同 | 动作取并集；不得只保留一个“最高等级”模型 |
| EC-04 | 一个模型允许同级、另一个同级模型禁止同级 | 分别计算后取可授予目标并集，不使用全局开关 |
| EC-05 | 模型被停用但仍有大量 Grant | 立即停止产生权限，Grant 留作审计和恢复，不触发资源×主体重写 |
| EC-06 | 动作从低等级调整到高等级 | 标准模型累计结果与引用该动作的自定义模型派生等级按新版本一致生效 |
| EC-07 | 动作被停用导致自定义模型无有效动作 | 该模型不得继续 active；系统 fail closed 并提示修复 |
| EC-08 | `CUSTOM` 资源在业务树中移动 | 结构父级改变，本级普通 Grant 保留，权限不自动继承新父级 |
| EC-09 | `INHERIT` 资源的父级被删除 | 删除方必须重挂、级联处理或拒绝；不能留下悬空权限来源 |
| EC-10 | OpenFGA 返回未知或超时 | 请求明确失败，任何旧路径不得补充 ALLOW |
| EC-11 | 迁移中部门成员发生变化 | 保留部门集合主体；最终权限按切换时的有效部门成员关系计算，不按旧快照展开 |
| EC-12 | 历史本级授权与继承授权重复 | `CUSTOM` 快照保留可追溯来源并做精确去重，不删除受保护属性 |
| EC-13 | 历史数据只有资源可见、没有具体动作 | 迁移后只保留可见关系，不推导下载、使用、编辑等动作 |
| EC-14 | 历史 `manage_*` 目标集合非连续 | 不自动套用新等级边界，进入人工映射且在处理前 fail closed |
| EC-15 | 启服后要求回退旧版本 | 不支持；重新进入维护并在新 model 与新控制面前向修复 |
| EC-16 | 正式迁移时仍有旧 API/Worker 实例存活 | 阻断迁移和启服，先停止全部权限读写实例 |
| EC-17 | 同一旧四档 tuple 有唯一 custom binding | 只按 binding 指向的迁移后模型创建 Grant，不再额外创建标准模型 Grant |
| EC-18 | 被编辑的旧系统模型与新标准模型动作不一致 | 创建历史自定义模型快照并迁移其原绑定，不污染新标准模型 |
| EC-19 | `include_children=true` 曾把一个根部门展开成多个子部门 tuple | 仅保留根部门 assignee 与范围，展开 tuple 只参与核对，不形成独立授权 |
| EC-20 | Config JSON 损坏、binding 指向缺失模型或同一 tuple 匹配冲突 binding | 记录原始定位并阻断相关迁移，不使用默认模型、空动作或最高等级猜测 |

---

## 6. 非功能验收

### 6.1 安全

- **NFR-01** — 未知动作、未分级动作、inactive 模型、异常 Grant 和权限服务故障必须默认拒绝。
- **NFR-02** — 任何客户端提交的模型等级、可授予范围、来源标签和可编辑状态均不可信，服务端必须基于当前有效事实决定。
- **NFR-03** — 权限成员名单、组织信息和模型影响范围属于受保护数据，只向明确有权角色开放。

### 6.2 一致性

- **NFR-04** — 模型发布、Grant 变更、权限模式切换和迁移批次必须幂等、可重试、可恢复，且不能对用户暴露半完成权限。
- **NFR-05** — 安全相关撤权、模型停用和同级策略收紧在成功返回后不得继续被旧缓存放行。
- **NFR-06** — 所有资源授权结果必须能追溯到同一租户内的有效模型、Grant 和主体来源。

### 6.3 性能与规模

- **NFR-07** — 修改一个已被大量资源和主体引用的 PermissionModel 时，授权数据写入量不得与“资源数 × 用户/部门数”成比例。
- **NFR-08** — 新增或撤销一个 Grant assignee 时，不得重写同一 Grant 中其他 assignee 或该模型在其他资源上的授权。
- **NFR-09** — 部门和用户组授权不得按成员展开；组织成员变化不得触发资源授权全量重写。
- **NFR-10** — 资源列表继续满足既有 cursor、批量候选和有界扫描契约；不得恢复为租户全量加载后逐项权限过滤再分页。
- **NFR-11** — 性能、容量和迁移时限的量化门槛在 Design 阶段基于生产脱敏分布确定，并作为发布门禁；本 Spec 不预设未经测量的数值。

### 6.4 兼容与可观测

- **NFR-12** — Platform 与 Client 的所有相关入口、频道独立授权入口及后台任务使用同一动作与 Grant 语义。
- **NFR-13** — 必须能按租户、资源类型、动作、模型、Grant 和来源观察权限判定、批量判定、候选枚举的数量、耗时、错误、拒绝原因及版本。
- **NFR-14** — 必须能观察模型影响范围、模型停用、Grant 变更、模式切换、迁移进度、差异、人工项、启服和前向修复状态。

---

## 7. 已确认产品决策

下列 OQ-01～OQ-07 已由用户在 2026-07-29 明确确认并回写；本节不存在剩余开放项：

| ID | 决策项 | 2026-07-29 确认结果 |
|----|-----------|---------------------|
| OQ-01 | `knowledge_library` 的 canonical 权限父级是什么？ | 与 `knowledge_space` 一样无上级，固定 `CUSTOM`；二者都可作为真实子文件/文件夹的直接父级 |
| OQ-02 | 新建动作等级与模型配置是平台全局还是租户级？ | `PLATFORM` 全局，仅平台超管配置；Grant/解析继续按 tenant 隔离 |
| OQ-03 | 第 4.2 节建议初始等级是否为产品最终映射？ | 采用第 4.2 节等级；具体资源 scope 见 Design §4.3 |
| OQ-04 | dashboard 是否纳入首批统一动作迁移？ | 纳入；覆盖成员管理、visible/edit/delete/manage_permission 和既有调用入口 |
| OQ-05 | 四个标准模型的初始“是否允许授予同级”分别是什么？ | viewer=false、editor=false、manager=false、owner=true；无 `manage_permission` 时该值不产生能力 |
| OQ-06 | 文件预览与下载如何鉴权？ | 预览不设置 PermissionAction；只有原件/打包下载检查 `download` |
| OQ-07 | 既有 F018 owner 交接在 F048 后是否继续开放？ | 选择 A：F048 启服时退役 F018，本期不实现 owner transfer；创建者 protected owner 保持不可转让，其他 owner 仍可并存 |

以下结论已由当前方案确认：

- `manage_permission` 的“是否允许授予同级”跟随 PermissionModel，每个模型可独立配置。
- 标准模型只允许修改上述模型级策略，名称、等级和动作集合不可修改。
- 自定义模型修改成功后影响所有引用同一模型的 Grant，不复制模型动作到资源和主体。
- PermissionGrant 表达“资源 + 模型”的授权主体集合。
- 同一用户的直接授权与部门授权是独立来源，权限取并集，撤销一个来源不影响另一个来源。
- 权限继承复用既有 `parent`，不新增 `permission_parent`。
- 复制资源时保留源资源的权限模式；`CUSTOM` 副本复制普通白名单，受保护授权按新资源规则生成。
- 对进入资源 ReBAC 的请求，OpenFGA 的具体动作结果是最终权限结论，不再由 Config 自定义模型做第二次裁决。
- 模型 `active` 是可授权和可生效的总开关，不是业务动作。
- 现有模型定义、模型动作和资源绑定迁入规范化关系表；Config 大 JSON 在切换后不再参与运行时。
- Authorization Model 沿用现有 Store；启动新镜像并由迁移门禁自动拒绝业务访问后，从
  backend 容器发布新 model、原地迁移并退役旧 tuple，校验后重启服务且只启用新 model。
  重启时允许按稳定
  Store name 自动发现唯一 Store 与最新 model，
  但必须再与 SQL CURRENT Catalog 的 ACTIVE release 严格匹配；禁止 dual/legacy client、
  同 tuple 双写或线上 shadow。
- 本期不支持独立迁移预演、回滚窗口或新→旧运行时恢复；失败保持维护并前向修复。
- Alembic revision 只负责数据库结构 DDL；正式权限数据迁移、OpenFGA tuple 更新与校验
  由 `src/backend/scripts/` 专用脚本在 schema upgrade 后执行，服务启动不自动迁数据。
- user-owned 资源必须建立受保护 owner；经 adapter 代码 allowlist 与 canonical business
  predicate 双重确认的 platform system-owned 资源不得伪造用户 owner，只由既有
  Constitution C4 system identity 管理。

---

## 8. 发布验收门槛

- 第 7 节所有产品决策已确认并回写。
- 本 Spec 通过 `/sdd-review features/v3.0.0-beta1/048-rebac-permission-model-grants spec`，并获得用户 ★ 确认。
- Design 完成 Authorization Model 升级、控制面、发布一致性、API、缓存、自动访问门禁直迁状态机和前向修复设计，并通过 Constitution Check。
- 动作映射和 `manage_*` 转换规则由产品、后端、安全和测试共同签署。
- 标准模型、自定义模型、模型停用、同级策略、多来源并集、模式切换和受保护授权均有自动化验收。
- 直接授权 + 部门授权 + 撤销直接授权的规范示例通过端到端测试。
- OpenFGA 故障注入证明不存在 Config、creator 或旧关系的 ALLOW fallback，且系统级身份策略不会因故障被临时启用。
- Alembic 单 head、DDL-only 和 MySQL/DM8 schema upgrade 验证通过；revision 不包含 DML、
  业务 import 或 OpenFGA 调用。
- `src/backend/scripts/` 专用权限数据迁移脚本在新镜像 backend 容器内完成，HTTP/WS 迁移
  门禁生效、ready F048 runtime heartbeat 为零，所有阻断项为零，其他差异均有批准记录。
- MySQL、DM8、Platform、Client、频道入口、后台任务及既有高频列表性能回归通过。
- 同 Store 新 model 启服、前向故障处置和旧运行数据退役均完成验证。

---

## 9. 设计与实现（指针，不复制）

| 你想知道 | 去哪看 |
|---------|--------|
| OpenFGA 类型、relation、具体动作和同源授权表达 | `design.md` §3～§4 |
| PermissionModel / PermissionGrant 数据结构与租户边界 | `design.md` §4 |
| 模型发布、active、并发和缓存失效协议 | `design.md` §4～§6 |
| API、错误码、Platform / Client 交互 | `design.md` §6 |
| 迁移脚本、checkpoint、批次、启服和前向修复 runbook | `design.md` §8 |
| 测试矩阵、任务拆解、执行顺序 | `tasks.md` |

---

## 相关文档

- [v3.0.0-beta1 Release Contract](../release-contract.md)
- [产品可读：Authorization Model 接管与数据迁移说明](./product-authorization-model-and-migration-guide.md)
- [旧版 F004 ReBAC Core](../../v2.5.0/004-rebac-core/spec.md)
- [旧版 F006 权限数据迁移](../../v2.5.0/006-permission-migration/spec.md)
- [旧版 F007 Resource Permission UI](../../v2.5.0/007-resource-permission-ui/spec.md)
- [旧版 F008 资源 ReBAC 适配](../../v2.5.0/008-resource-rebac-adaptation/spec.md)
- [F027 ReBAC 列表性能优化](../../v2.6.0/027-rebac-list-perf-optim/spec.md)
- [F036 ReBAC 逐项评估成本优化](../../v2.6.0/036-rebac-eval-cost-optim/spec.md)
- [F040 ReBAC 读路径性能收尾](../../v2.6.0/040-rebac-read-path-perf-rollout/spec.md)
- [PRD：3.0-beta1 ReBAC 逻辑优化](https://dataelem.feishu.cn/wiki/TYmHw4nPzitTQnkUjW8c5NFKnQg)
- [OpenFGA：Immutable Authorization Models](https://openfga.dev/docs/getting-started/immutable-models)
- [OpenFGA：Model Migrations](https://openfga.dev/docs/modeling/migrating/migrating-models)
- [OpenFGA：Tuple 与 API 最佳实践](https://openfga.dev/docs/getting-started/tuples-api-best-practices)
- [OpenFGA：Modeling Roles](https://openfga.dev/docs/best-practices/modeling-roles)
