# F117 主线设计与分支适配

遵守 `docs/constitution.md` C1–C8。主线起点 `cbd755b3ebab083b366922fb54ed545bc94cfccf`，已包含 F116 和成员来源重新激活修复；来源优化 `c4fc2316d`。

## 1. 背景

`/info` 已执行入口 visible 判断，却又展开全部动作。客户端分享入口只需 visible，按钮通过独立 `my-permissions` 获取，重复展开可从详情读取链路移除。现有统计/装饰查询仍保留，用阶段指标定位其成本。

## 2. 范围

只修改 `get_space_info`、详情 actions 字段说明及 info/广场共享的有效订阅状态展示函数。DAO、权限运行时、接口入口与前端不修改。不把中粮整段 service 或其它定制合入主线。

## 3. 方案与取舍

| 决策 | 原因与替代方案 | 何时重评 |
|---|---|---|
| 复用 visible，只输出入口标记 | 不展开全部动作；删除 actions 会破坏分享页判断。按钮继续经统一权限摘要读取。 | 有已确认的其它消费者需要完整动作时 |
| 实际可见优先，撤权清除陈旧已订阅 | 兼容部门/直接授权与主线退出后重入；不能照搬来源的不可见时原样返回 ACTIVE。 | 产品正式改变订阅与有效授权的关系时 |
| 保留所有原有业务查询与执行顺序 | 本次不引入缓存、并行查询或统计口径变化；先消除多余动作展开并提供测量。 | 阶段实测证明还有明确瓶颈时 |
| 记录互不重叠的九个阶段 | 累计 prepare，finally 记录失败时间，异常继续抛出；不把服务计时当作端到端耗时。 | 增加真实独立处理阶段时 |

## 4. 当前实现

### 4.1 数据流

`入口加载与 visible → 成员数/成功文件数 → 创建人 → 订阅展示/角色 → visible 标记 → 部门 → 自动标签 → 重建租户检查 → 响应`。

入口复用 `_require_space_info_permission`。普通用户 `_has_joined_visibility` 复用已通过的可见性；超管仍查询个人实际可见范围，管理身份不等于加入。角色缺失且有内容权限时仍单次检查 manage_permission。角色只展示，不替代资源动作鉴权。

### 4.2 字段与状态约定

- `/info.actions`：`["visible"]` 表示可访问内容，`[]` 表示只能预览/申请；其它列表的 actions 语义不在本次调整范围。
- 实际可见 → subscribed；不可见且历史 subscribed → not_subscribed；不可见的 pending/rejected 保留原展示窗口。成员、审批及授权数据不变。
- 主线不新增 `download_action_enabled`。文件权限和下载控制仍使用主线实现。
- `knowledge_space_info` 指标包含 prepare、auth、member_count、file_count、creator、subscription_role、department、auto_tag、rebuild 的 `*_elapsed_ms`，以及 total、失败阶段/异常类型和身份解析计数。
- total 覆盖服务函数，不包含依赖注入、网关及响应序列化；身份解析耗时属于阶段内开销，不能与阶段耗时重复相加。

### 4.3 职责与保留项

Service 编排与指标；既有 DAO 读取业务数据；权限 application 继续完成统一鉴权。Schema 只更新已有字段说明，不变更数据库。主线的公开/审批分享预览不要求 is_released，不引入来源分支的广场上架限制。

## 5. 已知坑

| 分支差异 | 忽略后的后果与处理 |
|---|---|
| 主线已修复撤权后的陈旧 ACTIVE | 直接覆盖来源 helper 会恢复错误的已加入状态；保留不可见时清除 subscribed，并断言 info、广场一致。 |
| 成员角色仍可能残留 | 仅 `member_info.is_active and has_content_permission` 时赋成员角色；无权限预览不返回陈旧成员角色。 |
| 中粮新增下载 Catalog 开关 | 主线没有该字段，不迁移该分支及其阶段，避免改变主线下载契约。 |
| 分享预览与广场上架不同 | 保留主线 `_is_joinable_preview_space`，新增未上架公开/审批空间预览回归。 |
| 旧 AST 隔离测试不执行构造函数 | 为新增计时依赖和实例计数补齐 fixture；另用真实 service 和 ASGI 回归验证，不能仅依赖抽取测试。 |

## 6. 对外契约与验证

Incoming：已有登录身份、业务数据与统一权限决定。Outgoing：详情入口标记、订阅展示、原有统计/装饰与终态指标。没有新端点、模型、依赖或领域所有权变更；不修改 release INV。

本机运行知识、权限、managed、撤权重入、检索及公开访问联合回归。真实 JWT/OpenFGA、MySQL/DM8 和浏览器验收通过只读 opt-in 套件及手动清单另验。离线调用预算不作为主线实际提速幅度。

## 修订历史

2026-11-02：按用户要求适配既有 `/info` 优化，保留主线撤权、角色、分享预览与下载控制差异。
