---
name: e2e-test
description: >-
  为 BiSheng 生成和运行 E2E 测试。两种模式：
  (1) SDD 模式 — 基于 feature spec.md 的 AC 生成覆盖；
  (2) 自由模式 — 对指定页面/功能写测试。
  采用双层策略：API 端到端测试（pytest + httpx）+ 页面手动验证清单。
  自动处理认证、多租户隔离、权限检查、Radix UI 交互等常见问题。
  用法：/e2e-test [feature_dir] 或 /e2e-test <描述>
  当用户说"写 E2E 测试"、"端到端测试"、"E2E coverage"，
  或使用 /e2e-test 命令时触发。
---

# E2E Test Skill

## 概述

生成并运行 BiSheng 的 E2E 测试，覆盖 API 链路和 UI 交互流程。自动处理 JWT 认证、多租户数据隔离、OpenFGA 权限检查验证、UnifiedResponseModel 响应断言等 BiSheng 特有问题。

## 调用方式

```
/e2e-test <feature_dir>          # SDD 模式：基于 spec.md AC 生成
/e2e-test <描述>                  # 自由模式：对指定页面/功能写测试
```

示例：
```
/e2e-test features/v2.5.0/004-rebac-core
/e2e-test 为租户管理页面写创建流程测试
```

---

## 六步流程

### Step 1：模式识别

解析用户参数：

- **SDD 模式**：参数是 `features/` 开头的路径 → 读取该目录下的 `spec.md`
- **自由模式**：参数是自由文本描述 → 直接进入 Step 3

### Step 2：AC 分析（仅 SDD 模式）

读取 `<feature_dir>/spec.md`，从 AC 表格中分类：

**API 行为类**（自动化 pytest 测试）：
- CRUD 操作及响应格式
- 权限检查（允许/拒绝）
- 分页、过滤、排序
- 错误码返回（MMMEE）
- 跨租户访问拒绝

**UI 交互类**（手动验证清单）：
- 表单填写、按钮点击
- 列表展示、搜索过滤
- 弹窗/抽屉交互
- 路由跳转
- 权限控制（按钮隐藏/禁用）

**排除**：
- 纯样式/布局调整
- 纯内部状态逻辑

输出分类后的 AC 列表，作为测试用例依据。

### Step 3：基础设施检查

检查共享 helpers 是否存在：

```
src/backend/test/e2e/
├── conftest.py       # pytest fixtures（认证、client、cleanup）
├── helpers/
│   ├── __init__.py
│   ├── auth.py       # JWT 认证 + 用户创建
│   ├── api.py        # API 常量 + 通用 CRUD helpers
│   └── cleanup.py    # 数据隔离 + 安全 cleanup
└── test_e2e_xxx.py   # 各 Feature 的测试文件
```

如果不存在，按照 `references/test-template.md` 创建基础设施。
如果需要新增共享函数，先加到对应的 helpers 文件中。

### Step 4：生成测试

基于 `references/test-template.md` 生成测试文件。

**文件命名**：`src/backend/test/e2e/test_e2e_{feature_name}.py`

**强制生成规则（12 条）**：

1. **数据隔离（红线）**：测试数据统一 `e2e-{feature}-` 前缀（≥5 字符）。**禁止无条件删除所有资源**——cleanup 必须按前缀过滤，只删本套件创建的数据。E2E 运行前后，非测试数据必须保持不变
2. **双重 cleanup**：setup fixture 清理上次残留 + teardown 清理本次数据
3. **测试租户隔离**：使用专用 `test_tenant_id`，不影响正式租户数据。创建测试数据前先确保测试租户存在
4. **认证流程**：通过 helpers 获取 JWT token，注入到请求 headers。测试管理员和普通用户两种角色
5. **响应格式断言**：所有 API 响应必须断言 `UnifiedResponseModel` 格式（`status_code`, `status_message`, `data`）
6. **权限测试配对**：每个"允许"操作配对一个"拒绝"测试（不同角色/不同租户）
7. **共享 helpers**：导入 `test/e2e/helpers/` 的函数，**禁止在测试文件内重新定义**通用工具函数
8. **AC 追溯**：每个测试方法的 docstring 标注 `AC-NN: <描述>`
9. **API 验证**：数据变更操作后，通过 GET 请求断言最终状态（不仅依赖创建响应）
10. **错误码精确断言**：业务错误断言具体的 MMMEE 错误码，不仅检查非 200
11. **串行执行**：使用 pytest-ordering 或 class 内方法顺序保证 setup → tests → cleanup
12. **幂等性**：测试可重复运行，不依赖特定的数据库状态（除测试自己创建的数据）

### Step 5：运行与修复

运行生成的测试：

```bash
cd src/backend
.venv/bin/pytest test/e2e/test_e2e_{feature_name}.py -v
```

如果失败，按照 `references/common-pitfalls.md` 的诊断表定位问题。

**最多 3 轮修复**。如果 3 轮后仍有失败，输出剩余问题让用户决定。

**调试技巧**：
```bash
# 单个测试
.venv/bin/pytest test/e2e/test_e2e_{feature}.py::TestE2E{Feature}::test_ac01 -v -s

# 显示完整请求/响应
.venv/bin/pytest test/e2e/test_e2e_{feature}.py -v -s --log-cli-level=DEBUG

# 只运行失败的
.venv/bin/pytest test/e2e/test_e2e_{feature}.py --lf -v
```

### Step 6：覆盖报告

输出 AC 覆盖表：

```markdown
# E2E 覆盖报告: <feature_name>

## API 测试结果

| AC-ID | 描述 | 状态 | 测试方法 |
|-------|------|------|---------|
| AC-01 | 创建租户成功 | ✅ 通过 | test_ac01_create_tenant |
| AC-02 | 重复租户名拒绝 | ✅ 通过 | test_ac02_duplicate_name |
| AC-05 | 表单提交创建 | ⏭️ 跳过（UI 交互，见手动清单） | — |

通过: N/M | 跳过: K（UI 交互类）| 失败: J

## 手动验证清单

生成位置: `features/v2.5.0/{NNN}-{name}/e2e-checklist.md`
覆盖 AC: AC-05, AC-06, ...

## 整体状态: PASS / PARTIAL / FAIL
```

---

## 手动验证清单格式

当 AC 涉及 UI 交互时，生成结构化验证清单。

**文件位置**：`features/v2.5.0/{NNN}-{name}/e2e-checklist.md`

```markdown
# E2E 验证清单: {feature_name}

**测试环境**: http://192.168.106.114:4001 (Platform) / :4001/workspace (Client)
**前置条件**: <描述测试前需要的数据/账号>

## Platform 前端

### AC-05: <描述>
- [ ] 步骤 1: 以管理员登录 Platform (admin/admin123)
- [ ] 步骤 2: 导航到 <页面路径>
- [ ] 步骤 3: 点击 <按钮/元素>
- [ ] 步骤 4: 填写表单: <字段=值>
- [ ] 预期: <具体可观察结果，如 toast 提示、列表刷新>
- [ ] 验证: 刷新页面后数据仍存在

### AC-06: <错误场景描述>
- [ ] 步骤: <触发错误的操作>
- [ ] 预期: <错误提示内容>

## Client 前端（如适用）

### AC-07: <描述>
- [ ] ...

## 回归检查
- [ ] 相关页面（<列出>）正常加载，无 console 错误
- [ ] 既有功能（<列出>）不受影响
- [ ] 不同角色（管理员/普通用户）看到的内容符合权限设定
```

---

## 参考文件

生成测试前**必须阅读**以下参考文件：

| 文件 | 用途 | 何时阅读 |
|------|------|---------|
| `references/test-template.md` | pytest E2E 测试骨架模板 | 生成新测试文件时 |
| `references/common-pitfalls.md` | BiSheng E2E 常见陷阱诊断表 | 测试失败时 |

---

## 已有共享 Helpers 清单

> 首次运行时由 Step 3 自动创建。以下是目标结构。

### `test/e2e/helpers/auth.py`

| 函数 | 签名 | 用途 |
|------|------|------|
| `get_admin_token` | `(client) -> str` | 获取管理员 JWT token |
| `get_user_token` | `(client, username, password) -> str` | 获取指定用户 JWT token |
| `create_test_user` | `(client, admin_token, username, role_id) -> dict` | 创建测试用户 |
| `auth_headers` | `(token) -> dict` | 构建认证请求头 |

### `test/e2e/helpers/api.py`

| 导出 | 用途 |
|------|------|
| `API_BASE` | 后端 API 基础 URL 常量 (`http://localhost:7860/api/v1`) |
| `assert_resp_200(resp)` | 断言 UnifiedResponseModel 成功响应 |
| `assert_resp_error(resp, code)` | 断言 UnifiedResponseModel 错误码 |
| `create_resource(client, path, data, token)` | 通用 POST 创建 |
| `list_resources(client, path, token, params)` | 通用 GET 列表 |
| `delete_resource(client, path, resource_id, token)` | 通用 DELETE |

### `test/e2e/helpers/cleanup.py`

| 函数 | 用途 |
|------|------|
| `cleanup_by_prefix(client, path, prefix, token)` | 安全删除指定前缀的资源。**前缀必须 ≥5 字符**，否则抛错防止误删 |
| `ensure_test_tenant(client, admin_token, tenant_code)` | 确保测试租户存在（不存在则创建） |

---

## 新增 Helper 的规则

当测试需要新的共享函数时：

1. **认证相关** → 加到 `helpers/auth.py`
2. **API 请求/断言** → 加到 `helpers/api.py`
3. **数据管理/fixtures** → 加到 `helpers/cleanup.py`
4. **特定 feature 的 helper** → 留在测试文件内，不提取

提取标准：**2 个以上测试文件使用** → 提取到 helpers。
