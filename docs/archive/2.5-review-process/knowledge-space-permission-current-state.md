# 知识空间权限现状说明

日期：2026-04-17

## 目的

本文件用于说明知识空间当前权限实现的真实状态，重点回答两个问题：

1. 当前知识空间权限运行时真正依据什么生效
2. 资源权限模板中的 `permissions[]` 与知识空间运行时行为目前是什么关系

本文件描述的是当前代码现状，不代表未来最终设计。

## 当前权限模型的基本结构

知识空间当前采用两层权限表达：

- **关系层（relation）**
  - `owner`
  - `manager`
  - `editor`
  - `viewer`

- **运行时检查层**
  - `can_manage`
  - `can_edit`
  - `can_read`
  - `can_delete`

其中，运行时检查层与关系层的映射目前由 OpenFGA 授权模型固定定义：

- `can_manage -> manager`
- `can_edit -> editor`
- `can_read -> viewer`
- `can_delete`
  - 顶层资源：等价于 `owner`
  - 层级资源（如文件夹/文件）：可来自上级的 `can_manage`

因此，当前真正生效的是“关系层对应的粗粒度档位”。

## 知识空间当前 relation 的实际含义

按当前实现，大致可以理解为：

- `viewer`
  - 对应“可读”档位
  - 运行时通过 `can_read` 生效

- `editor`
  - 对应“可写”档位
  - 运行时通过 `can_edit` 生效
  - 同时也包含可读能力

- `manager`
  - 对应“可管理”档位
  - 运行时通过 `can_manage` 生效
  - 同时也包含写和读能力

- `owner`
  - 顶层最高档位
  - 在顶层资源上通常也是删除能力来源

## 知识空间运行时实际检查点

### 1. 读权限

知识空间读取类操作主要检查 `can_read`。

当前可见的典型位置：

- 获取空间读权限：`_require_read_permission(space_id)`
- 文件预览：`get_file_preview(file_id)`
- 获取空间标签：`get_space_tags(space_id)`

这意味着：

- 被授予 `viewer` 的主体可完成读取类操作
- `editor` / `manager` / `owner` 由于更高档位，同样可读

### 2. 写权限

知识空间修改类操作主要检查 `can_edit`。

当前可见的典型位置：

- 空间写权限校验：`_require_write_permission(space_id)`
- 新增空间标签：`add_space_tag(space_id, tag_name)`
- 删除空间标签：`delete_space_tag(space_id, tag_id)`
- 更新文件标签：`update_file_tags(space_id, file_id, tag_ids)`
- 批量添加文件标签：`batch_add_file_tags(space_id, file_ids, tag_ids)`

这意味着：

- `editor` / `manager` / `owner` 具备写能力
- `viewer` 不具备写能力

### 3. 管理权限

知识空间成员/协作者管理类操作主要检查 `can_manage`。

当前可见的典型位置：

- 成员管理权限校验：`_require_manage_permission(space_id)`
- 更新成员角色：`update_member_role(req)`
- 移除成员：`remove_member(req)`

这意味着：

- `manager` / `owner` 具备管理协作者能力
- `editor` / `viewer` 不具备这类能力

## 当前资源权限模板中的 `permissions[]`

系统管理中的“资源权限模板”允许管理员为关系模型配置 `permissions[]`。

例如，模板中可能会勾选：

- 查看空间
- 编辑空间
- 删除空间
- 管理协作者
- 下载文件
- 上传文件

这些字段当前会被：

- 前端读取和展示
- 后端保存到 relation model 配置中

但当前知识空间运行时权限判断**不会逐项读取这些 `permissions[]`**。

## 当前真实生效的部分

当前生效的是：

- 被授权成哪一个 `relation`
  - `viewer`
  - `editor`
  - `manager`
  - `owner`

然后系统再通过固定映射把它转换成：

- `can_read`
- `can_edit`
- `can_manage`
- `can_delete`

## 当前未生效的部分

当前未真正接入知识空间运行时鉴权的是：

- relation model 里勾选的具体 `permissions[]`

换句话说：

- `permissions[]` 当前更像“已保存的模板描述信息”
- 还没有成为知识空间各具体动作的运行时判定依据

## 一个具体例子

假设存在一个 relation model：

- 名称：`只读不管理`
- relation：`viewer`
- permissions：
  - 勾选：查看空间
  - 不勾选：下载文件、管理协作者

在当前实现中：

- 该模型授予出去后，本质上仍按 `viewer` 档位处理
- 知识空间运行时只会检查它是否具备 `can_read`
- 不会逐项去看模板里是否勾选了“下载文件”或“管理协作者”

因此，模板中的细项与最终运行时行为之间，当前并没有逐动作绑定。

## 当前现状的准确表述

当前不是“relation 完全没有和 permission 绑定”。

更准确的说法是：

- **粗粒度绑定已经存在**
  - `viewer/editor/manager/owner` 与 `can_read/can_edit/can_manage/can_delete` 已绑定

- **细粒度绑定尚未完成**
  - relation model 中的 `permissions[]` 尚未真正接入知识空间运行时鉴权链路

## 后续若要真正打通，需要补什么

如果后续要让模板里的 `permissions[]` 真正影响知识空间行为，至少需要补齐：

1. 定义每个 `permission id` 对应的业务动作
   - 例如：下载文件、上传文件、删除空间、管理协作者、管理标签等

2. 将知识空间服务中的权限检查，从仅检查 `can_read/can_edit/can_manage`
   扩展为“检查具体 permission 能力”

3. 明确 `relation` 与 `permissions[]` 的关系
   - `relation` 是授权等级
   - `permissions[]` 是该等级下的细粒度能力集合
   - 两者如何共同决定最终权限，需要有统一规则

## 本文件结论

知识空间当前权限实现的核心事实是：

- 运行时主要按 `relation` 的粗粒度档位生效
- 模板中的 `permissions[]` 已可配置、可保存、可展示
- 但尚未逐项驱动知识空间运行时权限判断
