# F114 · Developer Token 知识上传人（171 真实环境）

对照 `features/v2.6.0/114-developer-token-knowledge-uploader/test-cases.html`。脚本覆盖 **TC-F114-ADM-01、API-01～04、SYNC-01/02**；未配置对应 `E2E_F114_*` 时用例会 **skip**（避免误连环境乱建数据）。

## 要起的服务

- 毕昇后端已部署本次代码，`config.yaml` 的 `database_url` 指向 **171**（或你希望打到的环境）。
- 已执行迁移：`cd src/backend && uv run alembic upgrade head`（`developer_token.knowledge_uploader_user_id` 列存在）。

## 涉及的表（读/写）

| 表 | 行为 |
|---|---|
| `developer_token` | 创建测试 Token；API-04 临时 `UPDATE` 将 `knowledge_uploader_user_id` 置 `NULL`；SYNC 用例在 Token 上写入 **有效的** `file_sync_rule` JSON（经 `DeveloperTokenService._validate_file_sync_rule` 与门户分类/业务域校验） |
| `knowledgefile` | `SELECT` 断言 `user_id` / `original_uploader_id`（API-01/03/SYNC） |
| `user` | API-03：按 `external_id` 解析用户；SYNC-01：按责任人 `external_id` 解析 `user_id` |

**无 DDL**（无新建表或改字段）。

## 环境变量

### 通用（API-01 / API-03 / API-04 / SYNC）

| 变量 | 说明 |
|---|---|
| `E2E_F114_KNOWLEDGE_ID` | SPACE 知识库 `K1` |
| `E2E_F114_BIND_USER_ID` | Token 绑定用户 `U_bind` |
| `E2E_F114_UPLOADER_USER_ID` | 知识上传人 `U_up`（可与绑定用户不同） |
| `E2E_F114_DEPARTMENT_ID` | 创建 Token 时的 `department_id`（须满足绑定用户成员关系） |

**注意：** `U_bind` 在 API-01 / API-03 / API-04 中必须对 `K1` 有 **上传权**（根目录 `upload_file_to_space`）。API-02 单独使用 `E2E_F114_DENIED_USER_ID`，不要把它和 `E2E_F114_BIND_USER_ID` 设成同一人。

### API-02（AC-03）

| 变量 | 说明 |
|---|---|
| `E2E_F114_DENIED_USER_ID` | `U_denied`：对 `K1` **无**根目录上传权；脚本把 Token 绑定到该用户，`knowledge_uploader_user_id` 仍为 `U_up`（有上传权），预期 **拒绝**（业务码 `18040`），且无新 `knowledgefile` 行。**不要**给该用户租户/超级管理员角色，否则会在知识空间路径上绕过 ReBAC，用例失真。 |

### API-03（external_id）

| 变量 | 说明 |
|---|---|
| `E2E_F114_EXTERNAL_USER_ID` | `U_ext.user_id`（需对 `K1` 有上传权；断言时与解析结果一致） |
| `E2E_F114_EXTERNAL_ID` | `U_ext.external_id`（库内唯一、`delete=0`） |

### SYNC-01 / SYNC-02（`POST /api/v2/filelib/file/sync`）

依赖租户内 **首钢门户分类/业务域** 已配置且与规则一致（与 Admin 保存 `file_sync_rule` 相同校验）。

| 变量 | 说明 |
|---|---|
| `E2E_F114_FILE_SYNC_RULE_JSON` | 完整 `file_sync_rule` 对象 JSON 字符串（通常 **fixed** `business_domain` + **fixed** `target_space`，且 `category`/`domain`/`knowledge_id` 与 `config` 表 `shougang_portal_config` 及目标空间绑定一致） |
| `E2E_F114_SYNC_BIND_USER_ID` | 专用于 SYNC：**Token 的 `user_id`**，必须能通过 `DeveloperTokenService._validate_file_sync_target`（绑定用户对该规则目标库有上传权）。可与 `E2E_F114_BIND_USER_ID` 不同：前者服务 chunks/file，后者若仅 viewer 则 sync 会报 `19813`。 |
| `E2E_F114_SYNC_DEPARTMENT_ID` | 同步请求 `params.department_id`（字符串；须与责任人/调用方主部门解析一致） |
| `E2E_F114_SYNC_RESPONSIBLE_EXTERNAL_ID` | 仅 **SYNC-01**：责任人 `external_id`（须 **≠ `U_up`**，否则文件归属与上传人相同，断言无意；落库 `user_id`/`original_uploader_id` 应为该用户） |

SYNC-02 不传责任人参数，预期回落为 **知识上传人** `U_up`（代码路径：`FilelibSyncService._resolve_responsible_user` 无 `external_id` 时用 `knowledge_uploader_user_id`）。

### 171 上曾跑通的一组示例（请以你环境 OpenFGA / 门户配置为准）

前提：`alembic upgrade head` 已执行，`developer_token` 表含 `knowledge_uploader_user_id`；知识空间 `id=12`（示例名「测试权限」），`knowledge.business_domain_codes` 含 `SD`；门户 `shougang_portal_config` 含分类 `POL` / `POL-E0UI` 与业务域 `SD`。

| 变量 | 示例值 | 说明 |
|---|---|---|
| `E2E_F114_KNOWLEDGE_ID` | `12` | filelib/chunks 目标空间 |
| `E2E_F114_DEPARTMENT_ID` | `5` | 与用户 5 的主部门 `user_department` 一致 |
| `E2E_F114_BIND_USER_ID` | `5` | FGA `can_edit` on `knowledge_space:12` |
| `E2E_F114_UPLOADER_USER_ID` | `6` | 与绑定不同，且可上传 |
| `E2E_F114_DENIED_USER_ID` | `23` | `can_read` 且无 `can_edit`；**非** `userrole.role_id=1`，否则管理员会绕过 |
| `E2E_F114_EXTERNAL_USER_ID` / `E2E_F114_EXTERNAL_ID` | `1` / `admin` | `user.external_id` 唯一 |
| `E2E_F114_SYNC_BIND_USER_ID` | `5` | file/sync Token 绑定用户须能上传到规则目标库 |
| `E2E_F114_SYNC_DEPARTMENT_ID` | `"5"` | `params.department_id` 字符串 |
| `E2E_F114_SYNC_RESPONSIBLE_EXTERNAL_ID` | `gzx02` | 对应 `user_id=5`，与 `U_up=6` 不同 |
| `E2E_F114_FILE_SYNC_RULE_JSON` | 见下 | fixed 目标 `knowledge_id=12` + fixed 域 `SD` + `POL`/`POL-E0UI` |

```json
{"category":{"code":"POL","subcategory_code":"POL-E0UI"},"business_domain":{"mode":"fixed","code":"SD"},"target_space":{"mode":"fixed","knowledge_id":12,"folder_mode":"none"}}
```

## 命令

与仓库其他 e2e 一致，仅当显式设置 `BISHENG_E2E=1` 时才跑：

```bash
cd /Users/lkk/workplace/bisheng/src/backend
PYTHONPATH=/Users/lkk/workplace/bisheng/src/backend \
config=config.yaml BISHENG_E2E=1 BISHENG_BASE_URL=http://127.0.0.1:7860 \
E2E_F114_KNOWLEDGE_ID=<K1> E2E_F114_BIND_USER_ID=<U_bind> E2E_F114_UPLOADER_USER_ID=<U_up> E2E_F114_DEPARTMENT_ID=<dept> \
E2E_F114_DENIED_USER_ID=<U_denied> \
E2E_F114_EXTERNAL_USER_ID=<U_ext> E2E_F114_EXTERNAL_ID=<ext_string> \
E2E_F114_SYNC_BIND_USER_ID=<U_sync_bind> \
E2E_F114_FILE_SYNC_RULE_JSON='<JSON>' E2E_F114_SYNC_DEPARTMENT_ID='<dept_key>' \
E2E_F114_SYNC_RESPONSIBLE_EXTERNAL_ID='<responsible_ext>' \
  uv run pytest ../../e2e/developer-token-knowledge-uploader/test_f114_flow.py -v --tb=short
```

**TC-F114-ADM-01** 仅依赖已登录管理员 JWT（脚本用 `user_id=1` 签发 cookie），无需 `E2E_F114_*`。校验失败时 HTTP 常为 **200**，响应 JSON 内 **`status_code`: 422**（RequestValidationError 包装）。

## 清理

成功路径会删除本脚本创建的 `developer_token` 行；TC-F114-API-04 若中断可能在库里留下 `knowledge_uploader_user_id IS NULL` 的废 Token，请按 `developer_token.id` 手工删除或补全上传人。SYNC 成功会在目标库留下 `knowledgefile` 行（如需清理请按 `file_id` 在环境内处理）。
