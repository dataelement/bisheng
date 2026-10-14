# 本地验证记录

- Status: `VERIFIED`（本地修复范围）
- Date: `2026-10-14`
- Branch: `feat/2.5.0-sg`
- Code State: 本次七个 Python 文件的工作区 diff；未提交、未推送、未部署。

## 结果

候选列表、目录列表及共享最终目标验证共用细粒度上传判断。固定目录 ID 保存时校验目录节点；路径规则仍沿用根目录预检。公共/部门类型、已发布状态、租户、业务域绑定和 Token 绑定用户主体保持不变。

## 证据

命令工作目录：`src/backend/`，复用既有 `.venv/bin/python`。

### E-001：修复前回归复现

```bash
.venv/bin/python -m pytest test/developer_token/test_file_sync_fine_grained_permissions.py -q
```

初始用例结果：`9 failed, 2 passed`。列表因 `relation_not_found` 返回空集，允许的保存目标被拒绝；固定目录校验收到 `folder_id=None`。随后增加的 SQLite、超过 200 个候选扫描和授权撤销用例不属于这次红灯证据。

### E-002：最终相关回归

```bash
.venv/bin/python -m pytest test/developer_token/ test/open_endpoints/test_filelib_sync_folder_target.py test/open_endpoints/test_filelib_sync_token_rule.py test/permission/test_knowledge_child_permission_check.py -q --disable-warnings
```

结果：`184 passed, 11 warnings in 3.27s`，exit 0。

覆盖：

- 实际细粒度计算配合模拟既有 FGA 关系模型；默认编辑权限及自定义只允许上传的权限模型均能进入候选。
- 自定义空权限不因通用编辑关系被错误放行。
- 权限过滤先于游标分页和搜索，超过 200 个数据库候选时不会漏掉后续上传目标。
- 深层目录授权仅展示必要祖先，祖先不获得上传权限；目录独立只读授权覆盖上级编辑授权。
- 根目录与固定目录允许/拒绝、目录错配，以及候选展示后撤销授权导致保存拒绝。
- 真实 SQLite 仓储执行证明租户、公共/部门类型、发布状态、目录类型和所属空间限制。
- Token 管理入口、绑定用户选择、换绑复核、共享同步目标错误映射和现有目录权限覆盖回归。

两个旧同步测试已模拟权限校验，但因后来新增的目录显示和审计依赖未隔离、既有响应 `tags` 字段未纳入断言而失败。本次仅补齐这些测试依赖和字段断言，同步生产代码与响应未改变。

### E-003：静态检查

- 七个 Python 文件通过 `compile(source, path, 'exec')` 语法检查。
- 对七个文件逐一运行 `scripts/arch-guard.sh`，无架构违规。
- Ruff 按相同配置对比当前文件与 `git show HEAD:<path>`，无新增规则/消息；存量诊断 119 项未扩大范围处理（KnowledgeSpaceService 109，仓储接口 9，仓储实现 import 排序 1）。
- 新回归文件 Ruff 检查为 0 个诊断，已按项目配置格式化。
- 本次追踪文件 `git diff --check` 通过；新增文件单独检查空白和换行。

## 验收矩阵

| Acceptance | Status | Evidence |
|---|---|---|
| AC-1 候选细粒度筛选、分页和搜索 | PASS | E-001, E-002 |
| AC-2 目录覆盖与必要导航祖先 | PASS | E-002 |
| AC-3 保存及共享最终目标上传判断 | PASS | E-001, E-002 |
| AC-4 身份、类型、租户与改动范围 | PASS | E-002, E-003 |

## 限制

- 本次没有访问或修改生产，没有修复旧用户 8531 的账号记录，没有扩展科室/团队/个人空间的固定候选范围。
- 没有真实 MySQL/DM8、真实 OpenFGA 服务或浏览器端到端验证；FGA 模型差异以可控模型模拟，数据库行为使用真实 SQLite。
- 候选权限现在需要计算范围内的空间和目录；已复用单阶段缓存并将并发限制为 16，尚未测量生产数据规模下的查询耗时。
- 用户既有 `fine_grained_permission_service.py`、前端目录权限及其他工作区修改保持原样；结果基于本地当前依赖状态。
