# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 写给后续 Claude 实例：本文只放「不读会写错的事」。代码地图、模块清单、节点枚举值等可 grep 出来的内容不在这里——需要更深的全景请查 `AGENTS.md`。

---

## 1. 项目身份

**BiSheng (毕昇)** — 企业级开源 LLM 应用 DevOps 平台。Monorepo，三大子工程：

| 路径 | 工程 | 技术栈 |
|------|------|--------|
| `src/backend/` | FastAPI 后端 + Celery Workers + Linsight Worker | Python 3.10+, uv, SQLModel, LangGraph |
| `src/frontend/platform/` | 管理/构建端（admin & builder） | Vite 5 + **Zustand** + react-query v3 + bs-ui |
| `src/frontend/client/` | 终端用户对话端（`/workspace` 基路径） | Vite 6 + **Recoil** + react-query v5 + shadcn/ui |


---

## 2. 常用命令

### 后端（cwd: `src/backend/`，所有命令前 `cd src/backend`）

```bash
# 依赖（uv，lockfile = uv.lock）
.venv/bin/python -V                                  # 必须是 3.10.x
uv sync --frozen --python .venv/bin/python

# 测试
.venv/bin/pytest test/                               # 全部
.venv/bin/pytest test/<module>/test_xxx.py::test_fn  # 单用例
.venv/bin/pytest test/ -k "keyword"                  # 关键字过滤
.venv/bin/pytest test/ -m "not e2e"                  # 排除 e2e
# 测试目录约束：新增测试按模块归档到 test/<module>/ (test/approval/、test/knowledge/…)，
# 不要再往 test/ 根目录堆。asyncio_mode=auto，async 测试函数不需要 @pytest.mark.asyncio。

# 格式化 / Lint（与 PostToolUse hook 一致）
.venv/bin/ruff format <file_or_dir>
.venv/bin/ruff check --fix <file_or_dir>

# 启动 API（端口 7860；config 必须是相对 bisheng 包目录的文件名）
export config=config.yaml
.venv/bin/uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log

# Celery（不同队列各开一个终端）
.venv/bin/celery -A bisheng.worker.main worker -l info -c 20  -P threads -Q knowledge_celery -n knowledge@%h
.venv/bin/celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery  -n workflow@%h
.venv/bin/celery -A bisheng.worker.main beat -l info

# 数据库迁移（Alembic，alembic.ini 在 src/backend/）
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "msg"  # 注意：autogen 只在 MySQL 反映准，达梦兼容需手工 review
```

### 前端

```bash
# Platform（管理端，端口 3001）
cd src/frontend/platform && npm install && npm start -- --host 0.0.0.0
# 商业版 Gateway 代理模式：
VITE_PROXY_TARGET=http://localhost:8180 npm start -- --host 0.0.0.0

# Client（终端用户，端口 4001）
cd src/frontend/client && npm install && npm run dev
```

### 一键中间件（Docker，仅基础设施，bisheng/前端跑本机）

```bash
bash docker/local-dev/start-middleware.sh   # MySQL/Redis/Milvus/ES/MinIO/OpenFGA
```

---

## 3. 后端写代码必读

### 3.1 分层架构（DDD）

```
api/router.py  →  api/endpoints/  →  domain/services/  →  domain/repositories/  →  数据库
                                          ↑
                                    domain/models/ + domain/schemas/
```

**仓储优先**：新功能默认 `api → service → repository → database`。
- Service 不直接拼 ORM 查询。
- Endpoint **不直接** `import bisheng.database.models.*`（arch-guard RULE-3 会告警，迁移期 WARNING）。
- 现有 DAO（`database/models/<x>.py` 里的 `get_xxx()` / `aget_xxx()`）是存量兼容层，**不要为新业务扩展 DAO 入口**——除非是在原有代码里做最小修复。

**新建领域模块**：① 在 `src/backend/bisheng/` 下建 `<module>/{api,domain}/` → ② `<module>/api/router.py` 创建 APIRouter → ③ 在 `bisheng/api/router.py` 注册。

### 3.2 双库兼容红线（MySQL + 达梦 DM8）⚠️

**所有新功能必须同时跑通两种方言**，达梦不是可选项。

| 场景 | 用这个 | 不要用 |
|------|--------|--------|
| JSON 字段 | `bisheng.core.database.dialect_helpers.JsonType` | `sqlalchemy.JSON`、`mysql.JSON` |
| 大文本 | `dialect_helpers.LargeText` | `LONGTEXT`、`MEDIUMTEXT` |
| 更新时间 | `dialect_helpers.UPDATE_TIME_SERVER_DEFAULT` | 手写 `ON UPDATE CURRENT_TIMESTAMP` |
| 表/列/索引存在性检查 | SQLAlchemy `inspect()` 或 `core/database` helper | `information_schema`、`DATABASE()` |
| JSON 内容查询 | 拆成显式关系列 | `JSON_EXTRACT`/`JSON_UNQUOTE`/`JSON_CONTAINS`/`JSON_SEARCH` |

**新增 spec/tasks 必须显式声明双库兼容**，且至少一个方言级验证任务。

注：开发机若为 macOS，达梦驱动 (`dmPython`/`dmAsync`) 不会安装（pyproject.toml `sys_platform != 'darwin'` marker）——本地无法跑达梦真实验证，CI/Linux 上才能跑。

### 3.3 多租户：tenant_id 自动注入

23+ 张业务表带 `tenant_id`。**不要手动 WHERE tenant_id = X**——SQLAlchemy event 已经做了：
- 读：查询自动注入过滤
- 写：插入自动填充当前 `current_tenant_id` ContextVar
- Celery：发送时 header 写 tenant_id，Worker 执行前恢复 ContextVar
- 存储：MinIO 路径前缀 / Milvus collection 前缀 / ES index 前缀 / Redis key 前缀都按租户隔离

`multi_tenant.enabled=false` 时行为等同单租户（默认 `tenant_id=1`），代码无须分支判断。

### 3.4 权限：五级短路 + ReBAC（OpenFGA）

权限检查链路（任一级命中就短路）：

1. `system:global` 的 `super_admin` → 全权
2. 资源 `tenant_id` 不匹配当前用户租户 → 拒绝（安全底线）
3. `tenant:{id}` 的 `admin` → 租户内全权
4. **ReBAC**：OpenFGA owner ⊃ manager(`can_manage`) ⊃ editor(`can_edit`) ⊃ viewer(`can_read`)
5. RBAC：`WEB_MENU` 仅控制前端导航可见性

**不要直接查 `role_access` 做资源授权**——arch-guard RULE-8 会拦。统一入口：

```python
from bisheng.permission.domain.services.permission_service import PermissionService
await PermissionService.check(...)        # 权限校验
await PermissionService.authorize(...)    # 创建资源时写 owner 元组
```

资源创建时**必须同步写 OpenFGA owner 元组**（通过 `PermissionService.authorize`）。失败会进 `failed_tuples` 补偿表。

### 3.5 API 约定

```python
# 认证注入
from bisheng.common.dependencies.user_deps import UserPayload
user: UserPayload = Depends(UserPayload.get_login_user)
# WebSocket 用 UserPayload.get_login_user_from_ws

# 统一响应
from bisheng.common.schemas.api import resp_200, resp_500, UnifiedResponseModel
return resp_200(data)
return resp_500(code, msg)

# 分页：新代码用 PageData[T]（data + total）；PageList[T]（list + total）是旧版兼容
```

**错误码**：5 位 `MMMEE`（模块 3 位 + 错误 2 位），定义在 `common/errcode/`。模块号速查：100=server, 101=finetune, 104=assistant, 105=flow, 106=user, 108=llm, 109=knowledge, 110=linsight, 120=workstation, 130=chat/channel, 140=message, 150=tool, 160=dataset, 170=telemetry, 180=knowledge_space。三种输出：`return_resp()`（HTTP）/ `to_sse_event()`（SSE）/ `websocket_close_message()`（WS）。

### 3.6 JWT / Cookie

Token 在 Cookie 名 `access_token_cookie`，也支持 Header / WS query。Payload `{user_id, user_name, tenant_id}`。Cookie 默认过期 86400s（`cookie_conf`）。

---

## 4. 前端开发速查

两个 React 工程**约定不能混用**，按目录自动适配（`.claude/rules/{platform,client}-frontend.md` 通过 globs 自动加载）。

| 维度 | Platform (`src/frontend/platform/`) | Client (`src/frontend/client/`) |
|------|-------------------------------------|--------------------------------|
| 状态管理 | **Zustand** (`@/store/`) + Context（UI 局部） | **Recoil** (`~/store/`) |
| 服务端状态 | react-query **v3**（`useQuery({ queryFn })`） | react-query **v5** |
| 路径别名 | `@/` → `src/` | `~/`（或 `@/`）→ `src/` |
| HTTP 封装 | `@/controllers/request.ts` | `~/api/request.ts` |
| UI 库 | `@/components/bs-ui/` | `~/components/ui/`（shadcn） |
| 图标 | `@/components/bs-icons/` | `lucide-react` |
| i18n hook | `useTranslation()` → `t()` | `useLocalize()` → `localize()` |
| i18n 文件 | `public/locales/{lang}/{ns}.json`（多 namespace） | `src/locales/{lang}/translation.json`（单文件） |
| Toast | `toast({ title, variant: 'error' \| 'success', description })` | `showToast({ message, severity: 'error' \| 'success' })` |
| Confirm | `bsConfirm(...)`（bs-ui） | — |
| 工作流编辑器 | `@xyflow/react`（**不是** `react-flow-renderer`），节点在 `src/CustomNodes/` | — |

**通用硬规则**：TypeScript only / 函数组件 only / 单文件 ≤ 600 行 / `interface` for Props、`type` for 内部 / `handleXxx` 内部、`onXxx` props / 注释英文 / 禁止直接 `import axios` / **不要新引入 UI 库或状态库**。

**403**：两端响应拦截器都自动处理（重定向），业务代码不要再写 403 分支。

---

## 5. 架构红线（自动守卫）

`scripts/arch-guard.sh` 在每次 Write/Edit 之后由 PostToolUse hook 同步执行。8 条规则，违反立刻在 stderr 提示：

| # | 规则 | 严重度 |
|---|------|--------|
| 1 | `common/`、`core/` 不导入 `domain/`、`api/` | VIOLATION |
| 2 | `database/models/` 不导入 `domain/` | VIOLATION |
| 3 | Endpoint 不直接导入 `database/models/` | WARNING（迁移期） |
| 4 | `domain/models/` 不导入 `domain/services/` | VIOLATION |
| 5 | API 层不跨模块互相导入 | VIOLATION |
| 6 | 前端 store 不直接调 HTTP（应走 `controllers/API/` 或 `api/`） | WARNING |
| 7 | 硬编码敏感信息（password/secret/token） | WARNING |
| 8 | DAO/Model 不直读 `RoleAccessDao` 做权限过滤 | VIOLATION |

**违反 VIOLATION 必须修**——这是 v2.5 重构留下的边界，不能再退化。

---

## 6. SDD（Spec-Driven Development）工作流

非琐碎 feature **走 SDD**。完整指南：`docs/SDD-Guide.md`，BiSheng 适配：`features/README.md`。

```
0. release-contract.md（每版本一次）
1. Spec Discovery → ★ 用户确认
2. spec.md
3. /sdd-review <dir> spec → ★ 用户确认
4. tasks.md
5. /sdd-review <dir> tasks（自动）
6. 拉 feature 分支 feat/<version>/{NNN}-{name}
7. 逐任务实现 → /task-review <dir> <id> → 打勾
7.5. /e2e-test <dir>（强制）
8. /code-review --base <主线分支>（自动）
9. 合并回主线
```

产物布局：`features/v{X.Y.Z}/{NNN}-{kebab-name}/{spec.md,tasks.md}`，模板在 `features/_templates/`。

**两个 ★ 暂停点不能跳过**。实现偏差必须记录到 `tasks.md` §实际偏差记录。

---

## 7. 高频踩坑清单

| 坑 | 真相 |
|----|------|
| `/api/v1/env` 的 `version` 字段 | **源码硬编码 `2.4.0`，不可靠**。判断后端代码版本走路由探测，不要依赖此字段。 |
| MinIO 图片 403 | Vite 的 `fileServiceTarget`（`vite.config.mts`）必须与后端 `config.yaml` 的 `object_storage.minio.sharepoint` **完全一致**，否则签名校验失败。 |
| `config.yaml` 中数据库/Redis 密码 | Fernet 加密，key 在 `core/config/settings.py` 的 `secret_key`。明文密码不能直接写入 YAML。 |
| 首次注册用户 | 自动成为系统管理员（`super_admin`）。多租户开启时必须先创建租户再注册用户。 |
| `BISHENG_PRO=true` | 启动后端**之前**设置，否则 `/api/v1/user/sso` 端点不开。 |
| 配置加载优先级 | `YAML → 环境变量(BS_*) → DB(initdb_config) → Redis 缓存(100s TTL)`。改了 DB 配置后等 100s 或清 Redis 才生效。 |
| Celery Beat 多租户 | Beat 会遍历所有活跃租户逐个执行定时任务，加任务时考虑 N 倍放大。 |
| API 代理两种模式 | 默认 Vite `/api/` → 7860；商业版 `VITE_PROXY_TARGET=http://localhost:8180` 经 Gateway。开发本地默认走第一种。 |

---

## 8. 项目级 Skills

`.claude/skills/`：

| 名称 | 用途 | 触发 |
|------|------|------|
| `i18n-localizer` | 提取硬编码中文 → i18n key，三套 locale 同步 | `/i18n-localizer` / "国际化这个模块" |
| `react-component-refactor` | 大组件拆分（hook 提取、子组件、目录重组） | `/react-component-refactor` / "重构这个组件" |
| `sdd-review` | spec/tasks 文档审查 | `/sdd-review <dir> spec` 或 `tasks` |
| `task-review` | L1 任务级合规检查 | `/task-review <dir> <task_id>` |
| `code-review` | L2 多维度代码审查 | `/code-review --base <主线>` |
| `e2e-test` | 生成 + 运行 API E2E 测试 + 手动验证清单 | `/e2e-test <dir>` |

---

## 9. 更深的全景

- `AGENTS.md` — 完整 600 行架构详解（部署架构、模块地图、子系统内部、Gateway 商业版、v2.5 迁移背景）
- `docs/architecture/` — 架构文档（含 `11-gateway.md`、`10-permission-rbac.md`）
- `docs/SDD-Guide.md` — SDD 方法论
- `docs/PRD/` — 产品 PRD（v2.5 权限改造、多租户管理、技术方案 Review）
- `docker/local-dev/README.md` — 本地一键开发环境
- `src/backend/README.md` — 后端 README

需要更细的数据流、节点类型、配置项分组——读这些。
