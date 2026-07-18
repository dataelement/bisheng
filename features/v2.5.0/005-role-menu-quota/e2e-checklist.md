# E2E 验证清单: F005-role-menu-quota

**测试环境**: http://192.168.106.114:4001 (Platform) / :7860/docs (API)
**前置条件**: 后端已运行，默认管理员 admin 可登录

## API 手动验证（需特殊用户设置）

### AC-04b: 部门管理员角色列表可见性
- [ ] 步骤 1: 创建一个部门（如"技术部"），将某用户设为部门管理员
- [ ] 步骤 2: 创建一个角色，department_id 设为技术部 ID
- [ ] 步骤 3: 以部门管理员身份调用 GET /api/v1/roles
- [ ] 预期: 只看到全局角色（只读）+ 技术部子树内创建的角色
- [ ] 验证: 不应看到其他部门创建的角色

### AC-10b: 普通用户调用角色管理 API
- [ ] 步骤 1: 以普通用户（仅有 DefaultRole）登录
- [ ] 步骤 2: 调用 POST /api/v1/roles 尝试创建角色
- [ ] 预期: 返回错误码 24003（RolePermissionDeniedError）
- [ ] 验证: PUT /roles/{id} 和 DELETE /roles/{id} 同样返回 24003

### AC-06: 租户管理员更新全局角色
- [ ] 步骤 1: 以租户管理员（非系统管理员）登录
- [ ] 步骤 2: 调用 PUT /api/v1/roles/2 尝试修改 DefaultRole
- [ ] 预期: 返回错误码 24003（全局角色对租户管理员只读）

## Platform 前端验证

> F005 为纯后端 Feature，前端改造归 F010。以下为 F010 前置验证。

### AC-13: 普通用户登录 web_menu
- [ ] 步骤 1: 以普通用户登录 Platform
- [ ] 步骤 2: 查看左侧导航栏可见菜单
- [ ] 预期: web_menu 包含该用户所有角色的菜单权限并集
- [ ] 验证: 调用 GET /api/v1/user/info，检查返回的 web_menu 字段

### AC-14: 管理员登录 web_menu
- [ ] 步骤 1: 以管理员登录 Platform
- [ ] 步骤 2: 查看左侧导航栏
- [ ] 预期: 看到所有菜单项（WebMenuResource 全集）
- [ ] 验证: GET /api/v1/user/info 返回的 web_menu 包含 workstation, admin, build, knowledge 等全部值

## 回归检查

- [ ] 旧角色管理页面（系统管理 → 角色管理）正常加载
- [ ] GET /api/v1/role/list 返回数据格式与改造前一致
- [ ] POST /api/v1/role/add 仍可创建角色（兼容旧前端）
- [ ] 不同角色的用户登录后，菜单可见性与角色配置一致
