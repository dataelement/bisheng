# F080 部署验收

本次修改未部署。离线路由/服务测试不代表真实 JWT、OpenFGA、MySQL/DM8 或浏览器性能已验证。

## 只读 API 套件

文件：`src/backend/test/e2e/test_e2e_cofco_managed_spaces.py`。默认跳过；只在部署新代码后的指定测试环境开启。已有测试空间和短期 token 由操作者准备，套件只发 GET，不创建或修改数据。不得在配置、日志或文档里填写凭据。

设置 `COFCO_MANAGED_E2E=1`、明确的 `E2E_API_BASE`、`COFCO_MANAGED_E2E_CASES`（JSON）及 token 环境变量；在 backend 执行 `pytest test/e2e/test_e2e_cofco_managed_spaces.py -v`。

CASE JSON 顶层：`ordinary`、`super_admin`、`restricted_super_admin`。每项含 `token_env`、`data_prefix`（以 `e2e-cofco-managed-` 开头）、非空 `fixtures` 数组。每个 fixture 含 `case_name`、`space_id`、`included`、`user_role`、`is_pinned`。收窄超管 token 必须由操作方确认是 `personal_only` 数据范围；`/user/info` 不能证明 token 的数据范围。

普通用户至少准备：创建者、管理员成员、部门/组授权的编辑者、无成员记录的 edit-only、无 edit 的 viewer、manage-only、不可见、取消发布、删除后残留 ID、其他租户 ID。全范围超管保留本租户列表；收窄超管只返回自身范围且可编辑的空间。API 套件检查显式 fixture 的包含/排除、角色、置顶、租户、字段和入选项 edit。缺失项不能只靠列表结果推断其具体拒绝原因。

## 手动与性能清单

- [ ] AC-01/04：上述身份与授权矩阵通过；按钮权限仍以 my-permissions 为准，实际文件/设置操作按各自权限校验。
- [ ] AC-02：可见枚举不可用、未完整结束或超过 5,000 上限时明确失败；不得悄悄返回部分列表。
- [ ] AC-03：固定可见量改变租户总空间量；固定租户量改变可见/可编辑量。记录 `knowledge_space_managed`、SQL 聚合、FGA 请求次数，确认没有全租户逐页扫描或逐资源 SELECT。
- [ ] AC-04：撤销 edit/visible、权限模式切换及发布过程中重复读取，不出现无编辑权限的入选项；Redis 标记异常时使用 HIGHER_CONSISTENCY。
- [ ] AC-05：浏览器管理页的名称/更新时间排序、置顶、角色、部门、根文件计数和跳转正常；与原版本同数据比较。
- [ ] AC-06：保存成功及失败的分阶段指标，阶段累计与服务总耗时一致；服务指标不含网关、依赖注入或序列化。
- [ ] AC-07：记录镜像 digest、源码提交、数据库版本和授权规模。冷/热分别重复测量 P50/P95；以相同普通用户与数据比较，不能用超管耗时或离线替身当优化效果。
