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
5. [平台模型](#5-平台模型暂未提供) —— 暂未提供
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
| `X-BiSheng-Access-Token` | 每请求的短时访问凭据句柄 | `retrieve` 用它代表**当前访问者**去检索；**不要自己解析、不要转存、不要当权限判据** |
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

### 出错了看哪一类

| 异常 | 说明 | 下一步 |
|---|---|---|
| `VisitorCredentialMissingError` | 本请求没有访问者凭据（直连了应用端口 / 后台任务 / 健康检查） | 经平台入口访问；后台任务不要检索 |
| `VisitorCredentialRejectedError` | 平台拒绝了这枚凭据 | 让用户刷新重进；**见下方「如实说明」** |
| `ScopeMissingError` | 本地期密钥缺 `knowledge:read` 能力位 | 找管理员给这把密钥勾上 |
| `TargetUnreachableError` | 指定的库里有不可及的（线上：未声明；本地：不存在/未授予） | 去掉它，或在清单里声明后重发 |
| `CapabilityRevokedError` / `CapabilityNotDeclaredError` | 能力被收回 / 从没声明过 | 找 owner 重新声明并重发 |
| `PermissionEvaluationError` | 权限引擎暂时不可用 | 稍后重试；**不要**改小范围重试 |
| `SdkIncompatibleError` / `PlatformTooOldError` | SDK 与平台版本不兼容 / 平台没发布 SDK | 从当前平台重新取 SDK；或联系管理员 |

> **如实说明（本轮）**：平台侧受理应用侧访问凭据的那一半**尚未上线**，所以现在调 `retrieve`
> 大概率答「凭据被拒」（`VisitorCredentialRejectedError`）。**这不是你的代码写错了，也不是密钥的问题，
> 换密钥没有用。** 按本章写法接好线即可，平台侧就绪后同一份代码直接生效。

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

## 5. 平台模型（暂未提供）

> **暂未提供。** 平台的「模型协议面」（让应用用 OpenAI 兼容客户端直接调平台管理的模型）
> **尚未上线**，本章随其一起补齐。在那之前：
> - **不要猜** base URL、不要拼 `BISHENG_PLATFORM_API_BASE + "/v1"` 之类的路径去试——那个变量是
>   **平台地址**，不是模型端点，现在没有任何模型端点在它下面。
> - 现在就需要调模型的应用：用应用**自己**的模型配置（地址、密钥都走环境变量引用，**不写进代码或清单**，
>   否则密钥扫描会拦），等平台面上线后再切换到平台注入的地址与凭据，届时模型名即模型管理里的原名、无档位转换。

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
- [ ] 没有拼任何模型端点地址；模型密钥只以环境变量引用出现。
- [ ] `bisheng dev` 起来后，通过**本地入口地址**访问，页面上显示的是你的服务账号名。
- [ ] 用了 SDK 的话：健康检查端点**没有**调 `auth.current_user()`；检索没有任何「取不到凭据就换一种身份」的分支；
      附件路径是应用内相对路径，代码里没有 bucket / 对象键 / 存储地址。

跑一次连通自检：`python selfcheck.py`（未 login / 平台不可达 / SDK 未装 / 版本不兼容 时各给一句可读原因；
在 `bisheng dev` 起的进程里跑还会检查数据库变量、身份注入、检索与附件三件套）。

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
