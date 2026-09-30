# 修复设计

## 根因与策略
旧 path 属于待修复数据，不能同时作为后代选择条件。保留 Department 模型/DAO 的既有落点，在 DAO 内抽取共享的事务内路径重建方法：从新父组织沿 parent_id 读取祖先，按真实子关系逐层、分批读取后代；在内存计算完整路径，验证完成后更新 ORM 实体并 flush，由调用者统一 commit。

- 不信任调用者的 parent_path/path 参数，保留原参数兼容已有调用。
- 用 ORM SELECT FOR UPDATE 锁定参与读取的组织，分批 IN（每批 400）控制参数量；不引入递归 SQL 或方言特有字符串函数。
- 以已加载组织的 tenant_id 检查父子关联，保留现有自动租户过滤；跨租户异常关系拒绝操作，不扩大租户可见范围。
- 明确拒绝父链环路、后代成环、缺失父级和过长路径；先完成规划，再变更实体，提交失败由已有 session 上下文回滚。
- 创建时先 flush 取得 ID，路径完成后一次 commit，避免原先同步新增分两次提交。
- 后台手动移动的循环校验改为父链校验，原权限和挂载检查继续保留；提交后事件保持原行为。
- 在同一事务内以真实祖先/后代复核既有“挂载点不得嵌套”规则，避免旧 path 使原检查漏掉挂载后代；不改变该规则。

## 文件边界
- `bisheng/database/models/department.py`：共享路径重建、两个同步写入入口。
- `bisheng/department/domain/services/department_service.py`：创建/移动复用事务内重建。
- `bisheng/sso_sync/domain/services/dept_upsert_service.py`：更新路径来源说明，不改变请求契约。
- `test/department/test_department_sync_reparent_paths.py`：真实 ORM 回归与多入口参数化。
- `test/test_department_service.py`：已有提交后事件测试的 DAO 边界适配（如需要）。
- `test/test_department_sso_dao.py`：仅补齐已存在模型字段的测试建表夹具，避免旧夹具缺列阻断相关回归。

## 验证及风险
V-001：SQLite 真实 ORM 参数化覆盖损坏后代、无关前缀、同父重算、新建、拒绝与回滚；覆盖三个变更入口。V-002：既有组织、SSO 同步和手工移动相关回归，定向 lint/语法/diff 检查。
锁语义依赖目标数据库，SQLite 不证明真实 MySQL/DM8 并发行为；不新增自动重试。正常小规模树采用按层查询，树很宽时分批。不会在启动时扫描并修复整租户；未经过这些入口的历史坏数据仍需另行确认后修复与刷新看板。
