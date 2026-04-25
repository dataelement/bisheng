# 权限问题成因分析

日期：2026-04-22

## 目的

本文件用于解释本轮权限相关 bug 的“成因模式”，不是继续罗列单点问题。

目标是回答：

1. 为什么这批 bug 会集中出现
2. 这些 bug 在开发历史上是如何形成的
3. 哪些 bug 其实是同一类根因的不同表现

关联文档：

- 总审计文档：[rbac-rebac-permission-audit-2026-04-22.md](/Users/zhou/Code/bisheng/docs/rbac-rebac-permission-audit-2026-04-22.md)
- 用户问题清单：[user-reported-permission-bugs-2026-04-22.md](/Users/zhou/Code/bisheng/docs/user-reported-permission-bugs-2026-04-22.md)

## 一句话结论

这批权限 bug 不是随机散点，而是 4 条开发轨迹叠加后的结果：

1. **F008 只把“资源关系判断”迁到了 ReBAC，但没有把所有“资源业务动作”一起迁过去**
2. **知识空间模块继续往“permission-first”演进，而其它资源模块停留在 relation / AccessType / membership 级别**
3. **部门知识空间、tenant 共享、部门管理员 overlay 是后加的能力，进一步放大了双轨权限的矛盾**
4. **前端系统管理与资源权限 UI 有历史兼容字段和占位入口，没有完全和后端运行时语义同步**

## 发展脉络

### 阶段 1：旧权限时代的基础结构没有被彻底移除

早期系统里，权限主要由以下结构承担：

- `role_access`
- `group_resource`
- `space_channel_member`
- 前端若干以 `user.role === 'admin'`、`frontend/backend` 之类 legacy key 为核心的判断

这些结构在后续 ReBAC 迁移后并没有被完全下线，而是保留为兼容层。

这决定了后续迁移天然不是“替换式重构”，而是“叠加式迁移”。

### 阶段 2：F007 / F008 把权限 UI 和 ReBAC 基础链路接入了，但重点仍是“关系级别”

关键提交：

- `6575bab62` `feat(F007): implement resource permission UI components and page integration`
- `17cc62a1f` `feat(F008): adapt 6 resource modules from RBAC to ReBAC (OpenFGA)`

这一阶段完成了两件大事：

1. 资源权限弹窗与授权 UI 成型
2. 一批资源模块开始把 `AccessType` 映射到 ReBAC relation

但这一阶段的重点其实是：

- `viewer/editor/manager/owner`
- `can_read/can_edit/can_manage/can_delete`

也就是“关系级别”的迁移。

并不是所有资源的所有动作都开始按 `permissions[]` 做细粒度控制。

这就埋下了后续的第一类问题：

- **relation 层生效了**
- **但 action / 页面入口 / 详情页 / 列表页并没有全部使用同一层判断**

### 阶段 3：知识空间模块继续向 permission-first 深化，和其他资源模块分叉

关键提交：

- `0dcb9abac` `Drive knowledge-space runtime auth from canonical permission templates`
- `c94ec024f` `Make knowledge-space permission-first semantics explicit`
- `11477ecbd` `Complete backend knowledge-space permission-first action coverage`
- `fafea3e90` `Align knowledge-space permissions around existing view/edit/delete semantics`

这几次提交把知识空间推到了一个更先进的状态：

- 不只看 relation
- 开始真正消费 `permissions[]`
- 详情、文件夹、文件、标签、删除、管理协作者等动作，都逐步进入 `_require_permission_id(...)`

但问题是：

- **知识空间走得更深**
- `assistant / workflow / tool / 旧知识库` 没有同步进入这一层

于是出现第二类系统性 bug：

1. 前端关系模型页面已经能配置应用/知识库/知识空间的大量具体权限项
2. 后端却只有知识空间真的消费这些 `permission id`
3. 其它模块还停留在 `AccessType -> can_read/can_edit` 或老逻辑

这就是为什么用户会感知到：

- “关系模型整体没生效”
- “列表能看，详情不能看”
- “勾了 use_kb 也没用 / 没勾 use_kb 也能进列表”

### 阶段 4：部门知识空间是快速插入的新资源层，叠加了 membership overlay

关键提交：

- `556aadbe9` `Establish department knowledge spaces as first-class backend resources`
- `927792b45` `Separate department-space upload approval from direct file ingestion`
- `f5edcd2d9` `Keep department-space approvals out of reviewer-owned uploads`
- `dfa6605e3` `Make department-space approval policy belong to each space`

这条线新增了：

- `department_knowledge_space`
- 部门管理员同步为知识空间 `ADMIN`
- 审批、系统创建、广场曝光等部门空间特性

这批能力是建立在原本 `knowledge_space` 的 permission-first 基础之上，但又引入了新的 overlay：

- `membership_source='department_admin'`
- `SpaceChannelMember` 同步
- 部门管理员不是自由加入，而是派生 membership

因此第三类问题开始出现：

1. **FGA relation**
2. **space_channel_member**
3. **department_knowledge_space binding**

同时参与同一个资源的行为判断。

这也是为什么会出现：

- 部门知识空间广场能看到，但详情报“已删除/已失效”
- 部门管理员能不能退出部门知识空间，语义不清
- 直接给知识空间授 owner，但“我的知识空间内容”仍看不到

本质不是一个点没写对，而是：

- **资源有多层身份来源**
- **各层没有统一主次关系**

### 阶段 5：Tenant tree / shared_to / child tenant admin 再次放大了权限判断分叉

关键提交：

- `b387f5703` `feat(F013-T08): PermissionService check inserts L3/L4 tenant gates`
- `ae32807bd` `feat(v2.5.1): F017 tenant-shared-storage`
- `909b22f4f` `feat(perm): ReBAC 应用列表异步化与部门管理员隐式范围修复`
- `2b3e8fb75` `Treat repeated OpenFGA tuple mutations as idempotent success`

这一阶段 `PermissionService.check()` 被继续增强：

- visible tenant gate
- child tenant admin shortcut
- shared_to / shared_with
- implicit dept-admin scope

但增强主要集中在：

- `check()`
- `list_accessible_ids()`
- tuple write stability

并没有同步把所有外围业务服务改成同一套入口。

于是第四类问题出现：

- **PermissionService 本身越来越复杂**
- **业务服务很多地方还在调用旧 helper / 旧 membership / 旧 AccessType**

这会产生非常典型的现象：

1. `check()` 通过，但列表里没有
2. FGA 中 tuple 在，但业务页不认
3. child tenant admin 能访问，但授权弹窗里档位不对
4. cache、membership、FGA 三边状态不同步

### 阶段 6：前端系统管理页和平台 shell 带着历史 key / 占位入口继续演化

关键提交：

- `813506955` `feat(F010): implement tenant management UI, login flow, and tenant switching`
- `94323e3ec` `fix(permission): dept admin role list, org access, user groups`
- `89649ffd7` `feat(perm-2.5): org member edit, primary dept, delete guard, router order`
- `fafea3e90` `Align knowledge-space permissions around existing view/edit/delete semantics`

以及更早的前端历史兼容：

- `frontend/backend` 菜单 key
- `role === 'admin'` 直接做入口判断
- `PermissionDialog` 的 share tab 占位

这造成了两类前端偏差：

1. **后端语义变了，前端入口判断没完全跟上**
2. **前端配置能力先出现了，但后端运行时只接了一部分**

典型例子：

- 工作台权限后端返回 `workstation`，前端入口还查 `frontend`
- 关系模型里能勾 `use_kb/view_kb/use_app`，但大部分运行时并不消费这些 id
- “链接分享”入口明明不支持，却作为 disabled tab 一直展示

## 归纳出的核心根因模式

### 根因 1：迁移不是替换式，而是叠加式

当前仓库不是：

- “旧逻辑被删掉，新逻辑接管”

而是：

- “旧逻辑还在”
- “新逻辑又加上去”
- “部分场景优先旧逻辑，部分场景优先新逻辑”

这类仓库最典型的问题就是：

- 双轨
- 覆盖
- 入口不一致
- 排障困难

### 根因 2：relation-level 已迁移，permission-level 只迁了一部分

F008 之后，大家容易以为“ReBAC 已经上线”。

但更准确地说：

- relation-level 基本上线了
- permission-level 只有知识空间模块走得比较深

所以用户所有关于“关系模型具体权限不生效”的反馈，其实大部分都属于这一类。

### 根因 3：列表、详情、管理动作不在同一个权限抽象层

当前很多资源都存在这种分裂：

- 列表：按 `can_read`
- 详情：按 `permission id`
- 管理动作：按 membership 或 creator
- “我的资源”：按 `space_channel_member`

这就是为什么用户经常会报：

- 列表能看，详情 403
- 详情能进，列表没入口
- 授了 owner，某些按钮仍灰

### 根因 4：资源层新增 overlay，但没有定义“哪一层才是主事实”

典型是知识空间：

- FGA relation
- `SpaceChannelMember`
- department-admin overlay
- department-space binding

如果没有明确规定：

- 哪一层是 source of truth
- 哪一层只是派生视图
- 哪一层只用于 UI 排序 / 订阅状态

那么所有“owner / manager / member / follow / department admin”都会混在一起。

### 根因 5：前后端模板仍有分叉

目前能看到至少两类模板：

1. 后端 canonical template
2. 前端 `RolesAndPermissions.tsx` 本地模板

虽然有一次提交开始让前端读取后端 knowledge-space template，但其它模块并没有同步统一。

所以又会出现：

- 前端可配置
- 后端不消费

或者：

- 前端 permission id 叫 `view_kb`
- 后端运行时要的是 `view_space`

## 为什么这些 bug 会在这两天集中暴露

从提交历史看，2026-04-16 到 2026-04-22 是权限和知识空间的高频变更期：

- `89649ffd7`
- `94323e3ec`
- `6575bab62`
- `556aadbe9`
- `927792b45`
- `f5edcd2d9`
- `dfa6605e3`
- `b387f5703`
- `909b22f4f`
- `2b3e8fb75`

这意味着最近一轮开发不是在“稳定层上修小 bug”，而是在：

- 权限模型继续收口
- 组织/部门/角色系统继续迁移
- 部门知识空间快速插入
- tenant gate / shared_to 又叠了一层
- 前端 UI 同期补齐

这类时期最容易暴露的，就是“跨抽象层的错位 bug”。

## 对当前用户反馈的映射

把你已提供的 bug 放回上述根因模型里，大致可以这样归类：

### A 类：历史结构残留

- 人员删除后 person_id 仍被占用
- 工作台菜单有权限但没有切换入口
- 链接分享入口应删未删

### B 类：作用域 / 主附表建模问题

- 角色更新时间不更新
- 角色名称跨部门不能重复

### C 类：relation-level 与 permission-level 分裂

- 清空关系模型权限后又被重置
- 知识库“可查看 / 可使用”配置与实际行为不一致
- 关系模型对应用/知识库整体不生效

### D 类：FGA 与 membership / overlay 双轨

- 知识空间 owner 授权后仍看不到内容
- 部门知识空间广场可见但详情报错
- 部门管理员是否可退出部门知识空间规则不清
- 助手 owner 授权后仍看不到助手信息

## 最终判断

当前权限问题的根因，不是“权限模型设计错了”，而是：

1. 设计已经进入 ReBAC + permission-first 的方向
2. 但落地还停留在“多代实现并存”的过渡态
3. 其中知识空间走得最快，角色/组织次之，助手/应用/工具/旧知识库更慢
4. 最近一轮又叠加了部门知识空间与 tenant tree，进一步放大了不一致

所以后续修复如果只按 issue 一个个打补丁，风险会很高。

更稳妥的方式应是：

1. 先明确每类资源的 source of truth
2. 再统一“列表 / 详情 / 动作 / 我的资源 / 权限弹窗”的判定层
3. 最后再逐条收敛用户 bug

否则会一直出现：

- 修了详情，列表坏
- 修了列表，管理动作坏
- 修了 direct grant，membership overlay 又打回去

## 本文件结论

本轮所有权限 bug，可以概括为一句话：

> **BiSheng 当前处在“从 legacy RBAC/overlay 迁移到 ReBAC/permission-first”的中间态，真正的问题不是单点判断错误，而是多套权限事实并存且未完全收口。**

## 对后续工作的启示与指导

这一节不是技术细节补充，而是给后续产品文档、开发实现、测试策略的统一指导。

---

### 一、对产品文档的启示

当前最大的问题之一，不是“代码没写”，而是**产品语义没有在文档中完全收口**。

很多 bug 背后其实都对应着一个文档层空白：

- direct grant 和 membership 是什么关系
- department admin 是不是 owner
- 列表可见和详情可读是不是同一层权限
- relation model 的 `permissions[]` 到底是不是运行时真实权限
- 哪些资源支持“链接分享”，哪些不支持

#### 建议 1：每类资源都要有一份“权限真值表”

建议后续产品文档对每一类资源单独明确：

1. 资源的主体类型
   - 例如：`knowledge_space`、`assistant`、`workflow`、`tool`
2. 资源的权限档位
   - `owner / manager / editor / viewer`
3. 资源的具体动作
   - 列表可见
   - 详情可见
   - 可使用
   - 可编辑
   - 可删除
   - 可授权
   - 可分享
4. 每个动作由哪一层权限决定
   - relation
   - permission id
   - membership overlay
   - tenant / department 派生身份

如果没有这张真值表，研发和测试都会默认“某动作大概跟可读差不多”，最后就会反复出现“列表能看、详情 403”这类问题。

#### 建议 2：明确 source of truth

每类资源都必须写清楚：

- 哪一层是权限主事实
- 哪一层只是派生展示
- 哪一层只是历史兼容

例如知识空间至少要明确：

- FGA relation 是不是主事实
- `space_channel_member` 是不是只用于订阅/置顶/排序
- department admin overlay 是不是系统派生，不允许用户主动退出

如果这件事不在 PRD 或技术方案里明确，代码实现一定会继续分叉。

#### 建议 3：文档里不要混用“查看 / 使用 / 可读 / owner / 管理者”这些词

当前一个明显问题是：

- 前端写的是“查看知识库 / 使用知识库”
- 后端运行时检查的是 `can_read`
- 知识空间详情又要求 `view_space`

所以文档中必须区分：

1. **关系档位**
   - owner / manager / editor / viewer
2. **运行时关系**
   - can_read / can_edit / can_manage / can_delete
3. **产品动作**
   - 查看列表
   - 查看详情
   - 使用知识库
   - 下载文件
4. **permission id**
   - `view_space`
   - `download_file`
   - `use_kb`

这四层一旦混写，产品、研发、测试都会以为说的是同一件事。

#### 建议 4：新增资源前，先定义“是否进入 permission-first”

以后每新增一种资源，产品必须先回答：

- 这类资源只做 relation-level 管理，还是要进入 permission-first
- 如果只做 relation-level，前端不应该暴露一堆细粒度 `permissions[]`
- 如果做 permission-first，就必须给出完整 permission id 清单和动作定义

否则就会再次出现：

- UI 可以配
- 后端不消费

---

### 二、对开发实现的启示

#### 建议 1：一类资源只能有一个权限主入口

后续实现必须避免：

- 列表走 `list_accessible_ids`
- 详情走 membership
- 管理动作走 creator
- “我的资源”走另外一张表

每类资源都应该先规定一个统一入口，例如：

- `resource_visibility_service`
- `resource_action_guard`

然后所有页面都从这一层派生，而不是各模块自己判断。

#### 建议 2：明确 relation-level 和 permission-level 的边界

现在最典型的问题是：

- F008 把 relation-level 接进去了
- 但 permission-level 只在知识空间里深入落地

后续开发必须先选一种路线，不能继续混：

1. **路线 A：所有资源都只看 relation-level**
   - 那就不要在前端暴露不生效的 `permissions[]`
2. **路线 B：所有资源逐步进入 permission-first**
   - 那就要为每种资源建立明确 permission id，并把运行时动作全部接进来

继续保持“知识空间是 permission-first，其他资源还是 relation-level + legacy helper”的状态，只会继续制造系统性 bug。

#### 建议 3：membership overlay 只能当派生层，不能和 FGA 并列做主判断

后续如果保留：

- `space_channel_member`
- department admin overlay
- user group overlay

那么必须明确它们只能承担：

- 订阅状态
- UI 排序
- pin / follow / pending
- 审批流上下文

不能再让它们和 FGA 同时承担“主权限判断”。

否则：

- direct grant 永远会和 membership 脱节
- owner / manager / member 的语义永远会混在一起

#### 建议 4：主表 metadata 和附表变更必须统一触发更新时间

角色问题已经说明：

- 改的是 `role_access`
- 用户看到的是 `role.update_time`

后续所有类似主附表结构都应统一处理：

1. 业务上视为“角色被修改”
2. 那就必须显式更新 role 主表更新时间

不要再把“更新时间”交给数据库被动触发，否则只要本次没碰主表，UI 就会失真。

#### 建议 5：删掉或封死旧入口，不要继续把兼容层当主路径

像下面这些入口，如果还允许继续改数据，就会不断制造新脏状态：

- `role_access/refresh`
- `group_resource` 资源管理
- 老的 `RoleAccessDao` 真实授权查询

兼容层如果必须保留，也应满足至少一条：

1. 只读
2. 灰度迁移专用，不暴露给日常业务入口
3. 明确写着 deprecated，且新功能禁止调用

#### 建议 6：避免 sync/async 双套权限 helper 并存

目前 `access_check()` / `async_access_check()` / `_run_async_safe()` 已经说明：

- 只要双套 helper 并存
- 调用方一旦用错上下文
- 就会出现 timeout / 假阴性 / 行为漂移

后续应尽量收敛为：

- 服务层只允许 async guard
- sync endpoint 明确在边界层适配

不要让每个业务函数自己决定走 sync 还是 async。

---

### 三、对测试策略的启示

#### 建议 1：权限测试不能只测接口 200/403，要测“同一资源的多入口一致性”

以后每个资源至少要做一组一致性测试：

1. 列表可见性
2. 详情可见性
3. 编辑动作
4. 删除动作
5. 授权弹窗中的权限档位
6. “我的资源”页是否出现

只有这样，才能发现：

- 列表能看但详情 403
- 授了 owner 但“我的资源”没有
- 详情能进但按钮灰掉

#### 建议 2：测试矩阵必须覆盖“授权来源”

现在很多 bug 只在某一种授权来源下出现。

后续测试矩阵至少要覆盖：

1. 资源创建者
2. direct user grant
3. department grant
4. user group grant
5. membership overlay
6. department admin overlay
7. tenant shared_to / child tenant admin

如果测试只覆盖“创建者”和“管理员自己建的资源”，绝大部分问题都测不出来。

#### 建议 3：要有“relation-level”和“permission-level”分层测试

每个资源都应分别验证：

1. 关系档位是否正确映射为 can_read/can_edit/can_manage/can_delete
2. 具体 permission id 是否真的影响对应业务动作

否则前端配置一个 `use_kb`，后端完全没消费，测试也不会发现。

#### 建议 4：必须加入缓存一致性测试

当前很多 bug 不是权限本身错，而是：

- 改完授权
- 旧缓存还在

后续测试要覆盖：

1. direct user grant 后立即访问
2. department grant 后立即访问
3. user group 成员变更后立即访问
4. 部门管理员撤销 / 添加后立即访问

至少要有一组测试验证“改权限后下一次请求是否立刻收敛”。

#### 建议 5：前端要有菜单 key / 入口权限的契约测试

像 `workstation` vs `frontend` 这种问题，本质上是契约断裂。

后续前端测试应明确校验：

1. `/user/info` 返回的 `web_menu`
2. 入口组件判断的菜单 key
3. 路由 permission key

三者必须一致。

#### 建议 6：对“占位入口”做 UI 审计测试

像“链接分享”这种永远 disabled 的 tab，不应靠人工长期盯着。

建议前端测试至少覆盖：

- 功能未开时不展示
- 功能开时可点击

而不是长期允许：

- 统一展示
- 永远禁用

---

### 四、建议的后续执行顺序

如果后续真的要收敛这批问题，建议按下面顺序走：

1. **先定规则**
   - 每类资源的 source of truth
   - relation-level 与 permission-level 的边界
   - overlay 的角色

2. **再定契约**
   - 菜单 key
   - permission id
   - 列表/详情/动作分别用哪层权限判断

3. **然后收旧入口**
   - `role_access`
   - `group_resource`
   - 历史 UI 占位入口

4. **最后逐资源修复**
   - 先知识空间 / 旧知识库
   - 再 assistant / workflow / tool
   - 最后 department knowledge space / tenant overlays

不建议直接按用户 issue 顺序打补丁。

因为当前很多 issue 是同一个根因在不同资源上的表现。

## 最终建议

从产品、开发、测试三个角度，最重要的统一原则只有一句：

> **以后不要再让“权限配置语义”“运行时权限判断”“列表入口逻辑”“详情动作逻辑”分别独立演化。它们必须被同一份契约和同一层主事实驱动。**
