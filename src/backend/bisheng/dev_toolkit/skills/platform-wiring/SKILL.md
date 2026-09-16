---
name: platform-wiring
description: >-
  让一个要托管到公司/企业「应用平台」上的应用接上平台能力：知道当前是谁在用（访问者身份由平台注入，
  应用绝不能自建登录页或自己做鉴权）、按当前访问者的权限检索知识库、存取应用自己的附件文件、
  使用平台给每个应用配的数据库（连接信息由环境变量注入）、
  以及在本机用 bisheng dev 把应用跑起来时拿到和线上完全同名的注入。
  当用户说到「怎么知道当前用户是谁」「要不要做登录」「用户身份从哪来」「按人隔离数据」
  「应用要存数据/建表/连数据库」「让应用查知识库/检索文档/问答只能答有权限的内容」
  「应用要让用户上传文件/存附件/下载报表」「本地怎么模拟平台环境」「bisheng dev」「调用平台的模型」
  「how does my app know who the user is」时触发——只要应用要托管到平台、又要用到身份、检索、
  附件或数据库，即使没点名平台也应触发。纯粹打包部署（不碰身份、不碰这些能力）用「部署纳管」技能即可。
metadata:
  display-name: 平台能力接线（访问者身份 / 知识库检索 / 附件存储 / 应用数据库）
---

# 平台能力接线

你的任务：让应用**用平台给的东西**，而不是自己造一套。平台已经替应用做了登录、做了数据库、做了本地
运行环境；应用只需要**读注入的头**和**读注入的环境变量**。本文件每一章都是「照做」而不是「参考」。

先读完目录再动手，**读的顺序就是目录的顺序**——第 1 章排在最前面不是偶然，它是唯一一个
「写错了应用照样跑起来、只是身份是错的」的地方。

1. [访问者身份](#1-访问者身份先读这一章) —— 有一个静默失败点，先读
2. [知识库检索](#2-知识库检索retrieve)
3. [附件存储](#3-附件存储storage)
4. [应用数据库](#4-应用数据库)
5. [平台模型](#5-平台模型openai-兼容) —— 地址与凭据都由平台注入，一个字都不要自己拼
6. [本地运行：`bisheng dev`](#6-本地运行bisheng-dev)
7. [自检清单](#7-自检清单)
8. [SDK 从哪来、为什么只有三件套](#8-sdk-从哪来与为什么只有三件套)

---

## 1. 访问者身份（先读这一章）

> ⚠️ **静默失败点——本包唯一一个，也是最贵的一个。**
> 应用**不要**自建登录页、**不要**自己校验密码、**不要**自己签发 session 或 token。
> 平台在应用前面有一层入口代理，用户在平台上已经登录过，代理把**当前访问者是谁**以请求头的形式
> 注入给应用；应用读头就是身份。
>
> 之所以叫静默失败：你自己写一套登录，应用**照样起得来**、预检**照样过**、审批**照样通过**、
> 健康检查**照样绿**——线上打开一看，要么用户被迫再输一遍平台上不存在的账号密码，要么你的应用
> 把所有人都当成同一个人。**没有任何一处会报错**。避免它的方法只有一个：这一节照做。

### 身份怎么来

每个经平台入口进来的请求都带这些头（名字**固定**，本地 `bisheng dev` 注入同一组）：

| 请求头 | 含义 | 备注 |
|---|---|---|
| `X-BiSheng-User-Id` | 当前访问者的用户 ID | **按人隔离数据用这个**，它稳定、唯一 |
| `X-BiSheng-User-Name` | 显示名 | 非 ASCII 会被 **百分号编码**（`%E5%BC%A0…`），显示前要 `urllib.parse.unquote` |
| `X-BiSheng-Tenant-Id` | 租户 ID | 单租户部署恒为一个值，一般用不上 |
| `X-BiSheng-Dept-Id` | 主部门的业务键 | **没有部门时 Dept 三个头都不存在**（不是空串） |
| `X-BiSheng-Dept-Name` | 主部门名称 | 百分号编码，显示前 `unquote` |
| `X-BiSheng-Dept-Path` | 主部门路径（自顶向下） | 百分号编码，显示前 `unquote` |
| `X-BiSheng-Subject-Kind` | 主体类型：`human`（真人）或 `service_account`（服务账号） | 线上恒为 `human`；本地 `bisheng dev` 期取决于你 login 用的密钥：服务账号密钥 → `service_account`，个人访问令牌 → `human` |
| `X-BiSheng-App-Id` | 本应用在平台上的标识 | — |
| `X-BiSheng-Access-Token` | 每请求的短时访问凭据句柄 | 两个去处：`retrieve` 用它代表**当前访问者**去检索（SDK 自动带上），调模型面时由你原样转发（[第 5 章](#5-平台模型openai-兼容)）。**不要自己解析、不要转存、不要当权限判据** |
| `X-BiSheng-Request-Id` | 请求关联 ID | 打日志时带上，平台侧能对上 |

读法就是读头，例如（标准库，无依赖）：

```python
from urllib.parse import unquote

def current_user(headers) -> dict:
    """平台入口注入的访问者。缺 User-Id 说明请求没走平台入口（本地直连应用端口）。"""
    user_id = headers.get("X-BiSheng-User-Id")
    if not user_id:
        return {"id": None, "name": "（未经平台入口）", "kind": None}
    return {
        "id": user_id,
        "name": unquote(headers.get("X-BiSheng-User-Name") or ""),
        "kind": headers.get("X-BiSheng-Subject-Kind"),
        "dept": unquote(headers.get("X-BiSheng-Dept-Name") or "") or None,
    }
```

### 三条不要

- **不要**读 cookie、不要解析 JWT、不要自己校验密码——平台会话 cookie 在入口就被剥掉了，应用拿不到，也不该拿。
- **不要**把请求头的值当**权限**用。头只回答「是谁」；「能做什么」是应用自己的业务规则（或后续平台能力）。
- **不要**在应用里做「切换身份 / 以某某身份查看」——本地和线上都没有这种入口，伪造头会在入口被剥离。

### 信任边界（为什么读头是安全的）

只有**经平台入口**进来的请求才带这些头，入口在转发前会**剥掉客户端自己带的任何 `X-BiSheng-*`**
（大小写、下划线/连字符的变体一并剥），再注入真值。所以：
- 应用**只**监听平台给的端口、**不要**再对外暴露第二个端口——绕过入口直连应用的请求没有身份头。
- 本地 `bisheng dev` 期同样如此：浏览器要访问的是 `dev` 打印的**本地入口地址**，不是应用自己的端口。

### SDK 用法：`auth.current_user()` 一行

平台发布了 Python SDK `bisheng-sdk`，上面那张表它已经替你读好了（装法见[最后一章](#8-sdk-从哪来与为什么只有三件套)）：

```python
from bisheng_sdk import auth

user = auth.current_user()      # 没有注入身份就抛错，不会返回 None
user.user_id                    # str，按人隔离数据用它
user.user_name                  # 已解码，不用自己 unquote
user.dept_name, user.dept_path  # 没有部门时是 None
user.subject_kind               # "human" / "service_account"
```

把当前请求交给 SDK 的三种接法，按你的框架挑一种（**只有这三种，别自己塞全局变量**）：

```python
# ASGI（FastAPI / Starlette）
app.add_middleware(auth.ASGIMiddleware)

# WSGI（Flask 等）
app.wsgi_app = auth.WSGIMiddleware(app.wsgi_app)

# 没有中间件钩子的框架（Streamlit 等）/ 测试：脚本顶部显式绑定
with auth.bind(incoming_headers):
    user = auth.current_user()
```

对照着看——**左边一行是对的，右边三种都是错的**：

| 正确 | 错误做法 | 为什么错 |
|---|---|---|
| `auth.current_user()` | 自建登录页 / 注册页 / 密码校验 | 用户在平台上已经登录过；再登一次的账号平台上根本不存在 |
| `auth.current_user()` | 自己读头再拼一套 user 对象 | 读头本身合法（见上表），但缺一处 `unquote`、把缺失的部门当空串、把 id 当 int，都是线上才发现的错 |
| `auth.current_user()` | 自己解析或校验 `X-BiSheng-Access-Token` | 那是给 `retrieve` 用的短时凭据，应用没有验签材料、也不需要——真伪由入口保证 |

几条必须知道的：

- **没有注入身份时 `current_user()` 抛 `PlatformIdentityMissingError`，不返回 `None`。** 这是刻意的：
  健康检查端点**不要调** `current_user()`（它没有身份头），后台任务 / 线程池里也不要假设有访问者。
  想「取不到就当匿名」的那一行，正是这一章开头说的静默失败点。
- `user_id` 是 **`str`**，而且**不是**平台 `user` 表的行号——别拿它做外键或去查平台用户。
- `subject_kind` 线上恒为 `human`；本地 `bisheng dev` 期**取决于你 login 用的密钥**（服务账号密钥 →
  `service_account`，个人访问令牌 → `human`）。要在页面上打「本地开发」角标就看这个字段。
- **本地看不到 per-user 差异**（本地只有你一个身份）。验证按人隔离的唯一路径 = **发布后用真实账号访问**。

---

## 2. 知识库检索（retrieve）

应用要「在用户有权限的知识库里查一段话」时，用 SDK 的 `retrieve`，**不要**自己去调向量库、
不要自己存一份索引、也不要拿应用自己的身份去查。

```python
from bisheng_sdk import retrieve

result = retrieve.search("报销标准是多少", knowledge_base_ids=[12, 13], top_k=5)
for chunk in result.chunks:
    chunk.content, chunk.document_name, chunk.chunk_index   # 可引用溯源
```

异步框架里用 `await retrieve.asearch(...)`，参数出参完全一样。

### per-user 语义（这一节决定会不会越权）

- **以当前访问者的身份检索**：执行身份来自本请求注入的 `X-BiSheng-Access-Token`，SDK 只负责把它带上。
  没有它就抛错，**不会**退回用应用自己的身份查——那是越权。
- **线上的可及范围 = 应用声明的知识库白名单 ∩ 当前访问用户的可见范围（到文件级）**。
  两层都在平台侧算：用户有权但应用没声明的库查不到，应用声明了但这个用户没权限的库和文件也不会出现。
  同一个用户在平台里自己检索，结果与经你的应用检索**集合相等**——不多给也不少给。
- **fail-closed**：没有访问者、凭据过期、权限引擎不可用、目标库不可及、能力被收回——一律**抛错**，
  绝不降级成「按白名单全量返回」或「返回空列表当成功」。空结果和失败在代码里是两件事。
- **后台任务没有访问者**，所以后台任务里调 `retrieve` 会抛错，本地线上一致。要预热就把查询放到请求里做。

### 本地 vs 线上（只会「本地看得少」，不会「本地能跑、线上越权」）

| | `bisheng dev` 本地 | 线上托管 |
|---|---|---|
| 执行身份 | 你 login 那把密钥对应的账号 | 当前访问用户 |
| 可及范围 | 该账号被**显式授予**的知识库（**没有**白名单这一层） | 声明白名单 ∩ 访问用户可见范围 |
| 凭据来源 | 本地入口每请求注入 | 平台入口每请求注入 |
| 差异后果 | 本地查得到、线上没声明 → 上线后被拒；本地查不到、线上用户有权且已声明 → 上线后查得到 |

所以**验证 per-user 差异的路径 = 发布后用真实账号访问**，本地复现不了。

检索要**两把**凭据，平台各用各的：应用自己的运行期凭据（环境变量 `BISHENG_APP_TOKEN`，答「哪个应用」，
平台据此取你声明的白名单）和每请求注入的访问者凭据（答「为谁做」，平台据此确立访问用户）。
两把都由平台注入、SDK 自己带上，**你不用写一行取凭据的代码**；重要的是知道它们不可互换——
只带应用凭据会被以「没有访问用户」拒绝，**没有 owner 兜底**。

### 出错了看哪一类

| 异常 | 说明 | 下一步 |
|---|---|---|
| `VisitorCredentialMissingError` | 本请求没有访问者凭据（直连了应用端口 / 后台任务 / 健康检查） | 经平台入口访问；后台任务不要检索 |
| `VisitorCredentialRejectedError` | 平台拒绝了这枚凭据：已过期、被伪造，或签给的是另一个应用 | 让用户刷新重进；本地见下方「如实说明」 |
| `AppCredentialMissingError` | 没有应用自己的运行期凭据（`BISHENG_APP_TOKEN` 未注入） | 线上：重新上线应用；本地 `bisheng dev`：见下方「如实说明」 |
| `ScopeMissingError` | 本地期密钥缺 `knowledge:read` 能力位 | 找管理员给这把密钥勾上 |
| `TargetUnreachableError` | 指定的库里有不可及的（线上：未声明；本地：不存在/未授予） | 去掉它，或在清单里声明后重发 |
| `CapabilityRevokedError` / `CapabilityNotDeclaredError` | 能力被收回 / 从没声明过 | 找 owner 重新声明并重发 |
| `PermissionEvaluationError` | 权限引擎暂时不可用 | 稍后重试；**不要**改小范围重试 |
| `SdkIncompatibleError` / `PlatformTooOldError` | SDK 与平台版本不兼容 / 平台没发布 SDK | 从当前平台重新取 SDK；或联系管理员 |

> **如实说明（本轮）：线上能用，本地 `bisheng dev` 还不能。**
> 线上托管期检索已经打通（前提是部署配好了访问者凭据的签发密钥；没配就没有访问者凭据，
> 平台一律拒绝而不是退回应用身份）。
> 本地 `bisheng dev` 期则有两处上游还没就绪：① 它**不注入** `BISHENG_APP_TOKEN`，所以本地先撞上
> `AppCredentialMissingError`；② 它本地自签的访问者凭据平台无从验签，补上①也会被拒。
> **两者都不是你的代码写错了，也不是密钥的问题，换密钥没有用**——按本章写法接好线，
> 本地先用别的方式验业务逻辑，检索的真实行为**发布后用真实账号验**。

---

## 3. 附件存储（storage）

应用要存用户上传的文件、或生成的报表时，用 SDK 的 `storage`，**不要**写进容器的本地目录
（根文件系统只读，`/data` 是给应用数据库的），也**不要**自己连对象存储。

```python
from bisheng_sdk import storage

meta = storage.put("报告/2026-Q1.pdf", data)      # data: bytes / 文件对象 / 路径
storage.stat("报告/2026-Q1.pdf")                  # 大小、类型、修改时间
storage.list("报告/")                             # 前缀列举
content = storage.get("报告/2026-Q1.pdf")         # 整读；大文件用 storage.open(...)
storage.delete("报告/2026-Q1.pdf")                # 逐个删，没有「清空」
```

六个函数各有 `a` 前缀的异步孪生（`aput` / `aget` / …）。

不变的几条（本地线上都成立）：

- **按应用隔离**：别的应用读不到、列不到、删不到你的附件；你也出不去自己的附件空间。
  路径穿越（`../`、绝对路径）会被当场拒绝，不会「规范化后放行」。
- **看不到底层实现**：没有 bucket、没有对象键、没有端点地址、没有存储凭据——应用只见**应用内相对路径**。
- **没有直链**：SDK 不返回任何 URL，也不产生匿名可访问的链接。要让用户下载，由你的应用自己把字节吐出去。
- **附件不计入租户的存储配额**，但单文件有上限，超了**报错而不是截断**。
- **没有「清空附件空间」这种操作**，删除只能逐个来。

本地与线上的差别：

| | `bisheng dev` 本地 | 线上托管 |
|---|---|---|
| 附件落在哪 | 项目下的本地附件目录（`bisheng dev` 注入） | 平台存储 |
| 生命周期 | 本地重启保留；**不进上传包、不进 git** | 实例回收 / 重建后完整；owner 删应用时随资产一并删除 |
| 单文件上限 | 只在注入了 `BISHENG_APP_STORAGE_MAX_FILE_MB` 时生效，否则不限 | 由部署配置决定（缺省 20 MB），恒生效 |

上一行是真实的坑：本地传 500 MB 通过、线上被拒。要提前撞上它，就在本地也注入同名变量。

> **如实说明（本轮）**：`bisheng dev` **还没有注入**本地附件目录变量，所以本地调 `storage`
> 会抛「没有存储句柄」（`StorageHandleMissingError`）。这同样不是你的代码问题；
> 在它补齐前，本地想跑通可以自己 `export BISHENG_APP_STORAGE_DIR=<项目>/.bisheng/attachments`
> 再启动——**变量名和线上完全一样，应用代码一个字都不用改**。

---

## 4. 应用数据库

平台给每个应用一个**自己的 SQLite 数据库**，数据在 `/data` 卷上、**跨版本发布保留**、别的应用碰不到。
应用只用标准库 `sqlite3`，**不引第三方 ORM**（构建不联网、少一个失败面）。

### 连接信息从环境变量读，不要写死

| 变量 | 线上取值 | 本地 `bisheng dev` 取值 |
|---|---|---|
| `BISHENG_APP_DB_PATH` | `/data/app.db` | `<项目>/.bisheng/dev/app.db` |
| `BISHENG_APP_DB_URL` | `sqlite:////data/app.db` | `sqlite:///<绝对路径>/.bisheng/dev/app.db` |

标准库用 `PATH` 那个；用 SQLAlchemy 之类才用 `URL`。两者指向同一个文件。

```python
import os, sqlite3

DB_PATH = os.environ.get("BISHENG_APP_DB_PATH") or "app.db"   # 本地直跑时退回当前目录

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")   # 多线程/多请求并发写更稳
    return conn
```

### 建表：应用自己建，用 `IF NOT EXISTS`

平台**不替你建表**（清单里的 `database.tables` 本轮只是声明，不产生任何 DDL）。在应用启动时执行：

```python
def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
```

**按人隔离**：凡是用户自己的数据，表里带 `user_id` 列，值就是 `X-BiSheng-User-Id`，查询时恒带 `WHERE user_id = ?`。

### 结构演进策略（升级版本时数据不丢）

数据卷跨版本保留，所以新版本代码面对的是**老结构的库**。规则只有两条：

1. **加列——自动、幂等。** 用下面这个模式，启动时跑一遍，已经有的列跳过：
   ```python
   def ensure_column(conn, table: str, column: str, ddl: str) -> None:
       existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
       if column not in existing:
           conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
           conn.commit()

   ensure_column(conn, "notes", "pinned", "INTEGER NOT NULL DEFAULT 0")
   ```
   新列必须**带默认值或允许 NULL**，老数据才能原样活下来。
2. **改列 / 删列 / 改表名——须确认，尽量不做。** 这类变更会让回滚到上一版的代码读不懂库。
   真要做：先加新列、双写一段时间、再在**后一个**版本清理旧列；发布时带 `bisheng deploy --confirm-schema-change`
   表示你知道自己在做什么。**如实说明**：本轮平台只**记录**这个确认、不做结构检测也不阻断——
   护栏在你这边，不在平台那边。

### 不要做的

- 不要往 `/data` 之外写库文件（根文件系统只读，运行期才炸）。
- 不要把库文件提交进 git、也不要指望它进上传包（`*.db` 默认排除，`.bisheng/` 硬排除）。
- 不要在两个进程里同时开同一个库做写操作（一个应用一个进程，平台就是这么跑的）。

---

## 5. 平台模型（OpenAI 兼容）

平台把自己管理的模型开成一个 **OpenAI 兼容面**：应用用官方 `openai` 客户端直连，地址和凭据由平台
以环境变量注入。**不要**自己配服务商账号、**不要**把模型密钥写进代码或清单（密钥扫描会拦），
**尤其不要自己拼地址**。

### 三个注入名（线上与 `bisheng dev` 同名）

| 变量 | 值 | 备注 |
|---|---|---|
| `OPENAI_BASE_URL` | OpenAI 兼容的 base URL | **已含 `/v1`**；官方客户端只在它后面拼 `/chat/completions`、`/models`，不会再补一段 |
| `OPENAI_API_KEY` | 这次调用用的凭据 | 线上 = 应用自己的运行期凭据（与 `BISHENG_APP_TOKEN` 同值）；本地 `bisheng dev` = 你 `login` 用的那把密钥 |
| `BISHENG_MODEL_BASE_URL` | 与 `OPENAI_BASE_URL` **同值** | 平台保留名，给不读 OpenAI 惯例变量的引擎 / 框架用 |

```python
from openai import OpenAI

client = OpenAI()          # 零配置：SDK 自己读 OPENAI_BASE_URL / OPENAI_API_KEY

completion = client.chat.completions.create(
    model="Qwen2.5-72B-Instruct",                      # ⚠️ 占位，换成你租户里真实存在的名字
    messages=[{"role": "user", "content": "一句话说明报销标准"}],
)
completion.choices[0].message.content
```

（本章所有示例里的模型名都是占位。怎么拿到真名、撞名了怎么写，见下一节。）

**地址一个字都不要自己拼。** `BISHENG_PLATFORM_API_BASE` 是**平台地址**、不是模型端点，在它后面接
`/v1` 之类的路径全是错的；平台对外只有一个模型地址出口，就是注入的 `OPENAI_BASE_URL`（它的值由平台在
`GET /api/v2/auth/whoami` 的 `model_base_url` 字段统一产出）。写死地址的应用换一个部署就调不通，
而且错得很难查——请求打到一个不存在的路径上，你只会看到 404。

**三个名字可能一个都没有**：这个部署没开放能力层、或者你的应用没声明任何模型时，平台**不注入**它们
（连你 shell 里同名的值也会被清掉，免得本地指向 api.openai.com 而线上调不通）。所以启动时就检查一次，
别拖到第一次调用：

```python
import os

MODEL_READY = bool(os.environ.get("OPENAI_BASE_URL") and os.environ.get("OPENAI_API_KEY"))
# MODEL_READY 为假时，把「本部署未开放模型能力」如实显示出来，不要退回自己的模型账号
```

### 模型名：写模型管理页上的原名，撞名了才写限定名

- **基准是模型管理页「模型名称」里那个名字**（不是显示名），大小写原样，不做任何档位 / 别名转换。
- 同一租户里两个服务商配了同名模型 → 裸名**歧义**，平台拒绝替你挑一个：返回 26214，并在错误体的
  `candidates` 里列出可用的**限定名**。限定名的写法固定是 `服务商名/模型名`，没有别的分隔符
  （`:`、`@`、`::` 都不认）。
- `GET {OPENAI_BASE_URL}/models` 返回的 `id` **恒可直接调用**：名称唯一时是原名，撞名时已经是限定名。
  另有扩展键 `bisheng_qualified_name`，恒为限定名——想在代码里写一个不受后来撞名影响的稳定名就用它。

```python
for model in client.models.list().data:
    model.id                        # 直接可填进 model= 的名字
    model.owned_by                  # 服务商名
```

### 只能调**声明过**的模型（这是线上与本地最大的差别）

线上托管期的可调范围 = **应用清单里声明的模型 ∩ 租户里在线的对话模型**，两层都在平台侧算：

```yaml
# bisheng-app.yaml
capabilities:
  models:
    - name: Qwen2.5-72B-Instruct     # 模型管理页上的原名；撞名时写「服务商名/模型名」
```

- 清单里**没声明**的模型：即使租户里有、即使你本地调得通，线上一律 26215。改声明要**重新发布**（走审批），
  不是改个环境变量就行。
- 清单里**一个模型都没声明**：平台连那三个变量都不注入——应用是「没有地址」，不是「调用时被拒」。
- 声明过的模型被管理员下线 / 服务商被删：26212 / 26213，应用的其它部分照常可用——只有这个模型调不动。

| | `bisheng dev` 本地 | 线上托管 |
|---|---|---|
| 凭据 | 你 `login` 那把密钥（需带 `model:invoke` 位，没有就 26003） | 应用自己的运行期凭据（位由清单声明推导） |
| 可调范围 | 该密钥所在**租户的全部在线对话模型**（**没有**声明这一层） | 声明 ∩ 租户在线模型 |
| 调用记录里的主体 | 那把密钥的服务账号 | 应用；转发了访问者凭据则是**当前访问用户**（见下） |

**所以本地调得通不代表线上调得通**：本地是租户全量，线上只有声明过的。上线前把要用的模型逐个写进
`capabilities.models`，比上线后看 26215 便宜。

### 访问者凭据：线上要转发，本地不要

线上每个请求注入给应用的 `X-BiSheng-Access-Token`（第 1 章的请求头表里那一行），应用调模型面时
**要原样带上同名请求头**，平台的调用记录才有「这次是为谁调的」这一维；不带**不报错**，只是记录里的主体
一律是「应用自身」，owner 事后查不出是哪个用户触发的。转发不改变可调范围——范围永远由声明决定。

```python
import os

IS_DEV = os.environ.get("BISHENG_APP_VERSION") == "dev"

def ask(question: str, incoming_headers) -> str:
    token = incoming_headers.get("X-BiSheng-Access-Token")
    # 本地 bisheng dev 期一定不要转发：那时 OPENAI_API_KEY 是服务账号密钥，
    # 服务账号密钥带这个头会被直接拒（26204），不是你的代码写错了。
    extra = {"X-BiSheng-Access-Token": token} if token and not IS_DEV else {}
    completion = client.chat.completions.create(
        model="Qwen2.5-72B-Instruct",
        messages=[{"role": "user", "content": question}],
        extra_headers=extra,
    )
    return completion.choices[0].message.content
```

**不要**在这里塞 `X-End-User` / `X-On-Behalf-Of`：本面不承载任何委托，带了就是 26205。

### 承诺面只有两条路径

| 能用 | 用途 |
|---|---|
| `POST {OPENAI_BASE_URL}/chat/completions` | 对话补全；`stream=true` 走 SSE |
| `GET {OPENAI_BASE_URL}/models` | 当前可调模型清单 |

其余 OpenAI 协议路径（`/embeddings`、`/completions`、`/responses`、`/images/*`、`/audio/*`…）一律
404 + 26201；Anthropic 的 `/messages` 单列 26202「本版仅提供 OpenAI 兼容面」。因此：

- **不要**把这个地址配给走 Anthropic 协议的客户端。
- **不要**指望在这里做 embedding——要按权限检索文档，用第 2 章的 `retrieve`。
- `n > 1` 会被拒（26203）：一次只要一个候选。枚举之外的请求字段原样透传给服务商，但平台不对它们作承诺。

### 出错了看哪一类

错误体是 OpenAI 形状（`{"error": {"message", "type", "code", "param"}}`），另带一个扩展键
`bisheng_code` = 下表的平台码（官方客户端会忽略不认识的键，可从异常的 `body` 里取；取不到就按 HTTP 状态分类）。

| 状态 / 码 | 含义 | 下一步 |
|---|---|---|
| 401 | `OPENAI_API_KEY` 没注入或已失效 | 线上：重新上线应用；本地：`bisheng login` 后重跑 `bisheng dev` |
| 403 / 26003 | 这把凭据没有 `model:invoke` 能力位 | 线上：清单声明模型后重新发布；本地：找管理员给这把密钥勾上 |
| 403 / 26204 | 这把凭据不接受访问者凭据 | 本地不要转发 `X-BiSheng-Access-Token`；线上转发的必须是本请求原样的那个 |
| 403 / 26205 | 本面不承载委托 | 去掉 `X-End-User` / `X-On-Behalf-Of` |
| 403 / 26215 | 模型没在清单里声明 | 加进 `capabilities.models` 并重新发布 |
| 404 / 26201 · 26202 | 端点不在承诺面 / 那是 Anthropic 路径 | 只用上表两条 |
| 404 / 26211 · 26212 · 26213 | 模型不存在（或不属于这个租户）/ 已下线 / 服务商已删 | 对着模型管理页核名字与状态 |
| 400 / 26203 | 请求不合法（如 `n > 1`、`model` 为空） | 照上一条改 |
| 400 / 26214 | 裸名歧义 | 改写 `candidates` 里给出的限定名 |
| 503 / 26216 | 可调范围暂时判不出 | 稍后重试；**不要**改小范围重试 |
| 429 / 26217 · 26233 | 服务商日调用上限用完 / 上游限流 | 日上限次日零点重置 |
| 502 / 26231 | 上游服务商失败 | 重试或换模型 |

两条流式专属的坑：

- `stream=true` 时，**范围与模型名的错误仍以普通 JSON 错误体返回**（平台先预取首块再发 200 头），
  所以别把「拿到 200 就等于模型选对了」写进逻辑。
- 已经开始流之后出错，SSE 里会先来一条 `data: {"error": {…}}` 再来 `data: [DONE]`。
  **一段没有内容就正常结束的流不等于成功**——错误事件要读，不能只看流有没有结束。

---

## 6. 本地运行：`bisheng dev`

在项目根（有 `bisheng-app.yaml`）执行：

```bash
bisheng dev            # 需要先 bisheng login 过；不校验任何权限位
bisheng dev --port 3000
```

它做三件事，全部和线上**同名**：

| 线上 | 本地 `bisheng dev` |
|---|---|
| 入口代理注入 `X-BiSheng-*` 身份头、剥离伪造头 | 内置迷你代理做同样的事；**身份恒为你 login 用的那把密钥对应的账号**（服务账号密钥 → `Subject-Kind=service_account`；个人访问令牌 → `human`） |
| `/data/app.db`，环境变量 `BISHENG_APP_DB_*` | `<项目>/.bisheng/dev/app.db`，**同名**环境变量；跨重启保留、不进上传包 |
| `PORT` / `BISHENG_APP_PORT` / `BISHENG_APP_BASE_PATH=/apps/<slug>` 等 | 同名注入；`BASE_PATH` 为空串（根路径） |
| 启动命令：`BISHENG_APP_START` → `Procfile web:` → `main.py` → `app.py` | 同一顺序 |

- 浏览器打开的是 `dev` 打印的**本地入口地址**（迷你代理），不是应用自己的端口——直连应用端口的请求没有身份头，
  这和线上绕过入口是一回事。
- 本地看不到「张三 vs 李四」的差异：本地不存在真实访问者，所有请求都是那个服务账号。**要验按人隔离，发布后用真实账号访问**。
- login 用的密钥**不会**进入应用进程的环境变量；应用里任何地方都不该需要它。

---

## 7. 自检清单

动手写代码前后各对一遍：

- [ ] 没有登录页、没有密码校验、没有自签 token；身份只从 `X-BiSheng-User-Id` 等请求头读。
- [ ] `X-BiSheng-User-Name` / `Dept-*` 显示前做了 `unquote`；缺 `Dept-*` 头当「没有部门」处理，不是报错。
- [ ] 用户数据表带 `user_id`，查询恒带 `WHERE user_id = ?`。
- [ ] 数据库路径读 `BISHENG_APP_DB_PATH`（或 `_URL`），没有写死；建表 `IF NOT EXISTS`；加列走 `ensure_column`。
- [ ] 没有改列/删列；真要做，走「加新列 → 双写 → 下个版本清理」并带 `--confirm-schema-change`。
- [ ] 没有拼任何模型端点地址（读注入的 `OPENAI_BASE_URL` / `OPENAI_API_KEY`，不碰 `BISHENG_PLATFORM_API_BASE`）；
      要调的模型都写进了清单的 `capabilities.models`；线上转发 `X-BiSheng-Access-Token`、本地不转发。
- [ ] `bisheng dev` 起来后，通过**本地入口地址**访问，页面上显示的是你的服务账号名。
- [ ] 用了 SDK 的话：健康检查端点**没有**调 `auth.current_user()`；检索没有任何「取不到凭据就换一种身份」的分支；
      附件路径是应用内相对路径，代码里没有 bucket / 对象键 / 存储地址。

跑一次连通自检：`python selfcheck.py`（未 login / 平台不可达 / SDK 未装 / 版本不兼容 时各给一句可读原因）。
想连身份、检索、附件三件套一起验：**另开一个终端让 `bisheng dev` 跑着**，在项目根再执行一次；
用了 `bisheng dev --port` 的话把它打印的**本地入口地址**作为参数传进来——
`python selfcheck.py http://127.0.0.1:3000`。传应用自己的端口验不出东西（那条路上没有注入头）。

---

## 8. SDK 从哪来，与为什么只有三件套

SDK 由**平台自己分发**，不需要公网：

```bash
# 本机开发：<平台地址> 就是你 bisheng login 的那个
pip install --extra-index-url <平台地址>/api/v1/dev-toolkit/simple/ bisheng-sdk
```

托管构建期**什么都不用配**：在 `requirements.txt` 里写一行 `bisheng-sdk` 即可，平台的构建环境
已经指向同一个索引。（装不上时先看 `<平台地址>/api/v1/dev-toolkit/versions` 的 `sdk` 段是不是 null——
是就说明这个部署没发布 SDK 安装件，找管理员。）

SDK 的版本**独立于平台版本**。平台会声明自己支持的最低 SDK 版本，太旧时你的应用会在第一次
`retrieve` / `storage` 调用得到一句明确的报错（含双方版本与处置方式），不会「看起来能跑、行为悄悄不对」；
反过来，平台升级**不需要**你重发应用。

**为什么 SDK 里只有 auth / retrieve / storage 三件套**：门槛是「平台特有」∧「写错了会出安全事故」。
模型调用和应用数据库两样都不满足——它们有成熟的标准库写法，平台只需把地址和凭据以环境变量注入，
再包一层只会多一个会漂移的中间物。所以 `bisheng_sdk` 里**没有**、以后也不该有 `chat` / `appdb`
之类的模块；模型见第 5 章，数据库见第 4 章。

---

## 参考

- `example/` —— 零依赖、可直接 `bisheng dev` / `bisheng deploy` 的最小样例：读身份头显示「你是谁」，
  按人存便签到应用数据库，含一次幂等加列。**不装 SDK 也能接线**，改造它比从零写更稳。
- `example-sdk/` —— 装 SDK 的 FastAPI 样例：三件套齐用（身份 / 检索 / 附件），
  健康检查端点刻意不调身份，每类异常都翻成一句给用户看的话。
- `selfcheck.py` —— 连通自检（登录态 + 平台可达 + 库变量 + SDK 版本 + 三件套各一次探测）。
- 「部署纳管」技能（`deploy-hosting`）—— 打包、清单、预检排障；本包假定你已经读过它的四条铁律。
