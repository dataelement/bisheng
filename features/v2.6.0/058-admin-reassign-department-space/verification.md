# Verification: F058 系统管理员调整部门知识库所属部门

**Feature ID**: `058-admin-reassign-department-space`  
**Date**: 2026-07-16  
**结论**: F058 专项后端测试、Client 定向测试、Python 静态检查、导入大小写检查和 Client 生产构建通过；真实 MySQL/DM8、真实 OpenFGA 补偿及浏览器人工冒烟待外部环境执行。

## 1. 自动化验证

| 验证项 | 状态 | 证据 |
|---|---|---|
| F058 后端 + 既有绑定回归 | PASS | `pytest -q test/knowledge/test_department_space_reassignment.py test/test_department_binding_admin.py` → `19 passed` |
| 后端 Ruff | PASS | F058 Repository、Schema、Service、依赖、路由和专项测试执行 `ruff check --select E4,E7,E9,F,I` → `All checks passed` |
| 后端格式 | PASS | 新增 Repository、Schema 和专项测试执行 `ruff format`/复核，无待格式化文件 |
| Client 抽屉权限与回显 | PASS | `CreateKnowledgeSpaceDrawer.test.tsx` 聚焦系统管理员/非系统管理员场景 → `2 passed` |
| Client API 契约 | PASS | `knowledge.test.ts` 聚焦 `reassignDepartmentSpaceApi` → `2 passed` |
| Client 保存编排 | PASS | `departmentSpaceReassignment.test.ts` → `3 passed` |
| Client 生产构建 | PASS | `vite build --mode ci` → `6082 modules transformed`，`✓ built in 34.20s` |
| 大小写导入检查 | PASS | `node scripts/check-case-sensitive-imports.mjs` → `All import paths match git index casing` |
| 差异检查 | PASS | `git diff --check` → exit code 0 |
| Client 全量 TypeScript | BASELINE_FAIL | 原工作树与 F058 工作树均为 `671` 个既有错误、exit code 2；F058 未增加错误数量 |
| ESLint | NOT_RUN | 已安装 ESLint 9，但仓库没有 `eslint.config.js/mjs/cjs`，命令在加载配置前退出；未为本特性修改全局 lint 配置 |

## 2. Acceptance Coverage

| AC | 状态 | 证据与说明 |
|---|---|---|
| AC-01 | PASS | Drawer 测试验证 `is_global_super` 用户可编辑且预选当前部门 |
| AC-02 | PASS | 非全局系统管理员组件只读；后端在任何数据库访问前以 `is_global_super` 拒绝 |
| AC-03 | PASS | SQLite 事务测试验证 binding、scope 和成员在同一事务更新，层级保持 `department` |
| AC-04 | PASS | 显式目标冲突与并发唯一冲突均转换为 `18002`，固定消息“目标部门已绑定知识库”；Client 错误传播测试通过 |
| AC-05 | PASS | Service/Repository 校验源 binding/scope、目标有效状态、租户归属；无效数据在事务提交前拒绝 |
| AC-06 | PASS | 相同部门幂等测试验证不调用 Repository 和 OpenFGA |
| AC-07 | PASS | OpenFGA operation 断言覆盖旧部门/子部门 viewer 撤销、新部门/子部门 viewer 授予和管理员 manager 迁移 |
| AC-08 | PASS | 事务测试验证纯手工成员保留、临时提升成员恢复原角色、新部门管理员按来源同步 |
| AC-09 | PASS | Service 以 `crash_safe=True`、`raise_on_failure=True`、`stop_on_failure=True` 调用批量权限写入；失败路径不返回成功 |
| AC-10 | PASS | 事务测试验证 `approval_enabled`、`sensitive_check_enabled` 保持不变；实现不更新知识库内容、文件、标签或创建者 |
| AC-11 | AUTOMATED_PASS / MANUAL_REQUIRED | 保存编排测试验证 active space 合并新部门并失效 `knowledgeSpaces`；真实浏览器刷新与侧边栏展示待人工冒烟 |

## 3. 基线失败对照

- `test_department_knowledge_space_service.py + test_approval_service.py`：F058 与原工作树均为 `8 failed, 12 passed`。8 个失败均在导入阶段报 `ModuleNotFoundError: bisheng.api.v1.schema`，不是 F058 引入。
- Client `tsc --noEmit`：F058 与原工作树错误数均为 `671`。主要为现有 request 返回值 `unknown`、历史 DTO 类型漂移及缺少 `openai` 类型声明。
- 定向 Drawer 测试有既有 React `act(...)` 警告，但 2 个目标用例均通过。
- Vite 构建仅有既有字体解析、Browserslist 数据、Tailwind 歧义、第三方 `eval` 和大 chunk 警告，退出码为 0。

## 4. 安全与工作树边界

- 后端使用 `login_user.is_global_super` 做权威授权，未依赖前端控件；子租户管理员不会获得归属调整权限。
- 请求体由 Pydantic 校验 `department_id > 0`；ORM 查询参数化并校验 tenant/status/scope。
- 目标唯一冲突只在确认目标绑定存在时转换为固定业务消息，其他完整性异常不伪装成业务冲突。
- F058 在独立工作树 `/Users/wenruli/code/project/bisheng/bisheng-f058`、分支 `feat/2.6.0/058-admin-reassign-department-space` 实现。
- F058 开始前识别到的 5 个 F057 未提交文件均未被修改或覆盖；最终核对时原工作树又出现 quota 相关并行改动，这些文件同样未进入 F058 工作树或差异。

## 5. 外部验证

- `MANUAL_REQUIRED`：在可回滚 MySQL 环境执行成功、冲突、相同部门和并发双请求，核对 binding/scope/member 事务结果。
- `MANUAL_REQUIRED`：在 Linux DM8 CI 执行同一后端专项测试，确认 `FOR UPDATE`、枚举比较和唯一冲突映射兼容。
- `MANUAL_REQUIRED`：连接真实 OpenFGA，验证成功后的 viewer/manager 结果；模拟 OpenFGA 不可用并确认 `FailedTuple` 留存和重试收敛。
- `MANUAL_REQUIRED`：浏览器使用系统管理员、子租户管理员和普通用户验证编辑态；验证目标冲突提示及刷新后侧边栏/详情新部门展示。
