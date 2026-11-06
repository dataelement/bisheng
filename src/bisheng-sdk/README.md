# bisheng-sdk

托管应用用的 Python SDK：三件「平台特有 ∧ 写错了会出安全事故」的事各封成一行到位的
默认做法，且这三行在 `bisheng dev` 本地与上线后**一字不改**。

```python
from bisheng_sdk import auth, retrieve, storage

user = auth.current_user()                      # 当前访问者；无注入身份即抛错
hits = retrieve.search("年假怎么休", knowledge_base_ids=[12])  # 以该访问者的身份检索
meta = storage.put("报告/2026.pdf", data)        # 存进本应用的附件空间
```

## 安装

从**你正在用的那个平台**取包（纯内网、匿名可达、无公网依赖）：

```bash
pip install --extra-index-url http://<平台地址>/api/v1/dev-toolkit/simple/ bisheng-sdk
```

托管构建期同样从这个索引装——在应用的依赖清单里写一行 `bisheng-sdk` 即可。

## 三件套

| 模块 | 做什么 | 最容易写错的地方 |
|---|---|---|
| `auth` | 读平台注入的访问者身份 | **唯一「写错了应用照样跑」的静默失败点**：不要自建登录页、不要自己解析凭据；无注入身份时 `current_user()` **抛错**而不是返回 `None` |
| `retrieve` | 以**当前访问者**的身份检索知识 | 执行身份必须是访问者而不是应用自己；后台任务没有访问者，检索一律被拒 |
| `storage` | 本应用附件空间的存取 | 只用应用内相对路径；没有 bucket / 对象键 / 直链，需要给用户下载就由应用自己吐流 |

**模型调用与应用数据库刻意不在 SDK 里**：模型用官方 OpenAI 兼容客户端 + 平台注入的
`OPENAI_BASE_URL` / `OPENAI_API_KEY`，数据库用标准库 + 平台注入的 `BISHENG_APP_DB_*`。

## 把当前请求交给 SDK

```python
# FastAPI / Starlette（ASGI）
app.add_middleware(auth.ASGIMiddleware)

# Flask（WSGI）
app.wsgi_app = auth.WSGIMiddleware(app.wsgi_app)

# Streamlit / 无中间件钩子的框架：脚本顶部显式绑定
auth.bind(st.context.headers).__enter__()
```

## 完整指南

`GET /api/v1/dev-toolkit/sdk-guide.md`（与「平台能力接线」技能包同源一份）。

## 本地开发

```bash
uv sync --frozen --extra dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
