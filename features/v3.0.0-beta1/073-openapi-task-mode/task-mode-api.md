# 任务模式 API 接口文档

> 适用版本：v3.0.0（发版线 `feat/3.0.0-beta2`）　·　可导入文件：[`openapi-v2-key-auth-api.json`](../053-openapi-auth-and-identity/openapi-v2-key-auth-api.json)
> 通用请求头、错误响应格式与身份模式见《[v2 密钥鉴权 API 接口文档](../053-openapi-auth-and-identity/openapi-v2-key-auth-api.md)》。

任务模式处理多文件、多步骤的复杂任务。调用方一次提交任务描述、附件、技能与模型，平台在后台异步执行；调用方凭任务标识查询状态、取回结果、下载产物。任务执行期间平台**不会向用户提问**：信息不足时按合理的默认假设推进，并在答复中写明所做假设。

## 1. 调用流程

```
① GET  /api/v2/workstation/config?run_mode=task      查询可用的模型、技能、工具（可在应用启动时查一次并缓存）
   GET  /api/v2/workstation/config/knowledge          查询可用的文档知识库、知识空间（分页）
② POST /api/v2/knowledge/upload                       上传附件，得到附件引用
③ POST /api/v2/workstation/chat/completions           提交任务（run_mode=task, execution=async），得到 task_id
④ GET  /api/v2/workstation/tasks/{task_id}            轮询状态，直到 completed / failed / terminated
⑤ GET  /api/v2/workstation/tasks/{task_id}/files/{file_id}   下载产物
   POST /api/v2/workstation/tasks/{task_id}/terminate  任一非终态时可终止
```

建议轮询间隔 5–10 秒。任务耗时从几分钟到一小时以上不等。

## 2. 权限与身份

| 项 | 说明 |
|---|---|
| 权限位 | 全部接口使用 `chat:invoke`，缺失返回 403 / `26003` |
| 个人访问令牌 | 不能调用任务模式 |
| 代表员工（`X-On-Behalf-Of`） | 按员工本人的权限执行；员工须有任务模式使用权限，否则 403 / `26063`。任务出现在员工工作台，员工可查看执行过程与产物 |
| 服务账号自身身份 | 按授权给服务账号的资源执行；建议传 `X-End-User` 区分外部使用者。任务不出现在任何人的工作台 |
| 归属 | 查询、下载、终止只能操作本调用主体提交的任务；换一个服务账号、换一个被代表员工或换一个 `X-End-User`，一律 404 |

**执行身份在任务执行期间失效时**：任务一旦提交成功，即使之后密钥被吊销、服务账号被停用或委托被撤销，已受理的任务仍会执行到结束；但此后的查询、下载、终止按每次调用时的身份判定，密钥失效后就取不到结果了。这一点与工作流异步任务不同（工作流在开始执行时会重新校验密钥）。

## 3. 查询可用配置

### `GET /api/v2/workstation/config?run_mode=task`

返回当前执行身份可用的模型、平台工具与已启用技能。不带 `run_mode` 或 `run_mode=daily` 时返回日常模式配置（与原接口一致）；其它取值返回 400 / `26017`。

```json
{
  "status_code": 200,
  "data": {
    "models": [{"id": "7", "name": "qwen-max", "displayName": "通义千问"}],
    "default_model_id": "7",
    "tools": [{"id": 3, "name": "联网搜索", "children": [{"id": 30, "tool_key": "web_search", "name": "联网搜索"}]}],
    "skills": [{"name": "contract-review", "display_name": "合同审阅", "description": "按公司模板审阅合同条款"}]
  }
}
```

- 提交时模型填 `models[].id`，技能填 `skills[].name`（不是 `display_name`，后者可能重复、可能被修改），工具填 `tools[].children[]` 的 `id` 与 `tool_key`。
- 查询结果中列出的项，提交时不会因「不存在」或「无权限」被拒；但它是一个时点快照，管理员停用技能、下线模型后，提交仍按当时状态校验。

### `GET /api/v2/workstation/config/knowledge`

| 参数 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | `library`（文档知识库）或 `space`（知识空间） |
| `name` | 否 | 按名称模糊搜索 |
| `cursor` | 否 | 上一页返回的 `next_cursor` |
| `page_size` | 否 | 1–100，默认 20 |

```json
{"status_code": 200, "data": {"data": [{"id": 12, "name": "合同库", "description": null, "update_time": "2026-09-20T10:00:00"}], "page_size": 20, "has_more": false, "next_cursor": null}}
```

只返回执行身份能用的文档知识库和能看到的知识空间。任务模式不支持问答知识库与个人知识库。

## 4. 上传附件

沿用 `POST /api/v2/knowledge/upload`（multipart，字段 `file`），返回 `{file_path, relative_path, file_name}`。提交任务时把 `file_path` 与 `file_name` 原样放进 `files`。

**附件从上传起 3 天内有效，且须在这 3 天内开始执行**（附件在任务开始执行时才被读取）。排队时间过长导致附件过期的，任务照常执行，结果中该附件标为 `expired`。附件只能由上传它的同一调用主体使用。

## 5. 提交任务

### `POST /api/v2/workstation/chat/completions`

与日常模式共用同一接口，以 `run_mode` 区分。任务模式返回 JSON，不是 SSE 流。

| 字段 | 必填 | 说明 |
|---|---|---|
| `run_mode` | 是 | 固定 `"task"` |
| `execution` | 是 | 固定 `"async"`；缺省或 `"sync"` 返回 400 / `26060` |
| `clientTimestamp` | 是 | 客户端时间，如 `2026-09-30T10:00:00` |
| `text` | 是 | 任务描述（客户应用内置的提示词放这里），1–20000 字符 |
| `instructions` | 否 | 业务上下文指令，≤ 4000 字符；叠加在平台规则之下，不替换平台规则 |
| `model` | 是 | 模型 id |
| `skills` | 否 | 技能名数组；不传则不加载任何技能 |
| `tools` | 否 | `[{"id": 30, "tool_key": "web_search"}]` |
| `knowledge_ids` | 否 | 文档知识库 id 数组，≤ 50 |
| `knowledge_space_ids` | 否 | 知识空间 id 数组，≤ 50 |
| `files` | 否 | `[{"file_path": "...", "file_name": "a.pdf"}]`，≤ 50 |

不接受 `conversationId`（每次提交新建会话，传入返回 400 / `26061`）；不接受契约外的任何字段（400）。任一入参不合法，整次提交被拒，不会创建任务。

```json
{"status_code": 200, "data": {"task_id": "3f2c…", "status": "queued", "queue_position": 3}}
```

## 6. 查询任务

### `GET /api/v2/workstation/tasks/{task_id}`

| `status` | 含义 | 附带字段 |
|---|---|---|
| `queued` | 已受理，排队中 | `queue_position`（可能为空：刚被取走、尚未开始的瞬间） |
| `running` | 执行中（含附件解析） | `progress: {done, total}`，尚未拆出待办时为空 |
| `completed` | 已完成 | `partial`（是否部分完成）、`result` |
| `failed` | 失败 | `failure: {category, message}` |
| `terminated` | 已被终止 | — |
| `waiting_input` | 预留，本期不会出现 | — |

`result` 结构：

```json
{
  "answer": "……（已去除内部引用标记；信息不足时会写明所做假设）",
  "files": [{"file_id": "a1b2", "file_name": "合同风险清单.docx", "file_type": "docx", "size": 20480, "primary": true}],
  "unavailable_deliverables": [{"file_name": "summary.pdf", "reason": "not_generated"}],
  "attachments": [{"file_name": "scan.tiff", "reason": "unsupported"}]
}
```

- `files[].primary = true` 的是主交付物。
- `unavailable_deliverables`：答复里提到但实际没有生成（`not_generated`）或格式损坏（`invalid_format`）的文件，不会出现在 `files` 里。
- `attachments`：未能使用的附件及原因：`unsupported`（类型不支持）、`failed`（解析失败）、`expired`（已过期）。单个附件不可用不会导致任务失败。

查询可重复进行：执行中进度只增不减，终态后每次返回完全一致；查询不影响员工在工作台里看到的实时进度。

**失败类别与处置**

| `category` | 含义 | 建议 |
|---|---|---|
| `content_filter` | 被模型服务商的内容审核拦截 | 调整任务描述或附件内容后重新提交，原样重试无用 |
| `quota_exhausted` | 模型额度用尽 | 联系管理员 |
| `auth_error` | 模型凭据无效 | 联系管理员 |
| `rate_limit` | 模型限流 | 稍后重新提交 |
| `service_unavailable` | 模型服务或平台队列暂不可用 | 稍后重新提交 |
| `network_timeout` | 网络超时 | 可重新提交 |
| `task_aborted` | 任务被中止（如执行节点重启） | 可重新提交 |
| `unknown` | 其它 | 查看 `message`；所选技能在执行前被停用时也归此类，`message` 会列出技能名 |

## 7. 下载产物

### `GET /api/v2/workstation/tasks/{task_id}/files/{file_id}`

返回文件流（`Content-Disposition: attachment`）。只能下载该任务 `result.files` 中的文件；平台不返回长期有效的直链。

## 8. 终止任务

### `POST /api/v2/workstation/tasks/{task_id}/terminate`

排队中、执行中的任务可以终止，终止后不可恢复、不产出结果，返回终止后的任务视图。已结束（`completed` / `failed` / `terminated`）的任务返回 409 / `26064`。

## 9. 错误码

| 场景 | HTTP | 错误码 |
|---|---|---|
| 缺少 `chat:invoke` | 403 | `26003` |
| 运行模式取值无效 | 400 | `26017` |
| 日常模式要求异步 | 400 | `26015` |
| 任务模式要求同步或缺少 `execution` | 400 | `26060` |
| 任务模式传入会话标识 | 400 | `26061` |
| 技能不存在或未启用（`data.unavailable` 列出技能名） | 400 | `26062` |
| 被代表员工没有任务模式使用权限 | 403 | `26063` |
| 终止已结束的任务 | 409 | `26064` |
| 内容未通过安全审查（`data.auto_reply` 为处置文案） | 400 | `26065` |
| 模型不存在、不可用或未上线（日常模式同） | 400 | `26066` |
| 平台工具不可用 | 400 | `26067` |
| 任务队列暂不可用（未创建任务，可稍后重新提交） | 503 | `26068` |
| 知识库不存在 / 类型不支持 / 无权使用 | 404 / 400 / 403 | 沿用知识库模块错误码 |
| 知识空间不存在 / 无权访问 | 404 / 403 | 沿用知识空间模块错误码 |
| 附件引用不属于当前调用主体 | 404 | — |
| 任务不存在或不属于当前调用主体 | 404 | — |
| 权限服务暂不可用 | 503 | — |

执行期失败不是 HTTP 错误，体现在任务状态的 `failure` 里（第 6 节）。

## 10. 完整示例

```bash
HOST=https://bisheng.example.com
KEY=bs-sak-xxxx
H=(-H "Authorization: Bearer $KEY" -H "X-End-User: emp-1024")

curl -s "$HOST/api/v2/workstation/config?run_mode=task" "${H[@]}"

curl -s -X POST "$HOST/api/v2/knowledge/upload" "${H[@]}" -F file=@contract.pdf
# → {"data": {"file_path": "https://…/tmp/open-api/…/9c1e.pdf", "file_name": "contract.pdf", …}}

curl -s -X POST "$HOST/api/v2/workstation/chat/completions" "${H[@]}" -H 'Content-Type: application/json' -d '{
  "run_mode": "task", "execution": "async", "clientTimestamp": "2026-09-30T10:00:00",
  "model": "7", "skills": ["contract-review"],
  "text": "审阅附件中的合同，列出风险条款和修改建议，输出 Word 文档。",
  "files": [{"file_path": "https://…/tmp/open-api/…/9c1e.pdf", "file_name": "contract.pdf"}]
}'
# → {"data": {"task_id": "3f2c…", "status": "queued", "queue_position": 1}}

curl -s "$HOST/api/v2/workstation/tasks/3f2c…" "${H[@]}"
curl -s -OJ "$HOST/api/v2/workstation/tasks/3f2c…/files/a1b2" "${H[@]}"
```

```python
import time, requests

BASE, HEADERS = "https://bisheng.example.com/api/v2", {"Authorization": "Bearer bs-sak-xxxx", "X-End-User": "emp-1024"}

def run_task(text, files, model, skills):
    body = {"run_mode": "task", "execution": "async", "clientTimestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "text": text, "model": model, "skills": skills, "files": files}
    task_id = requests.post(f"{BASE}/workstation/chat/completions", json=body, headers=HEADERS).json()["data"]["task_id"]
    while True:
        view = requests.get(f"{BASE}/workstation/tasks/{task_id}", headers=HEADERS).json()["data"]
        if view["status"] in ("completed", "failed", "terminated"):
            return view
        time.sleep(8)
```

## 11. 本期不支持

| 能力 | 调用时的表现 |
|---|---|
| 实时事件流 / 执行步骤明细 | 无对应接口，只能轮询状态 |
| 任务执行中向用户提问 | 不会出现；`waiting_input` 预留 |
| 在已有会话上续接或追问 | 传 `conversationId` 返回 `26061` |
| 任务模式同步（流式）执行 | 返回 `26060` |
| 日常模式异步执行 | 返回 `26015` |
| 个人访问令牌调用 | 返回 403 |
| 在途任务数上限、限流、配额、幂等键、回调通知 | 暂无；所有任务与工作台任务共用一个队列，先到先执行 |

## 12. 升级说明

**持有 `chat:invoke` 的存量服务账号密钥，升级后即可发起任务模式。** 任务模式会运行技能、执行代码，并长时间占用任务队列。升级后请管理员在「服务账号」页复核持有该权限位的密钥；不需要任务模式的集成，请改签不带 `chat:invoke` 的密钥。管理界面中该权限位已更名为「调用会话与任务」。
