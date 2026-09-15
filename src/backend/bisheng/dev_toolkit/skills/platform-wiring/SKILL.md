---
name: platform-wiring
description: >-
  让一个要托管到公司/企业「应用平台」上的应用接上平台能力：知道当前是谁在用（访问者身份由平台注入，
  应用绝不能自建登录页或自己做鉴权）、使用平台给每个应用配的数据库（连接信息由环境变量注入）、
  以及在本机用 bisheng dev 把应用跑起来时拿到和线上完全同名的注入。
  当用户说到「怎么知道当前用户是谁」「要不要做登录」「用户身份从哪来」「按人隔离数据」
  「应用要存数据/建表/连数据库」「本地怎么模拟平台环境」「bisheng dev」「调用平台的模型」
  「how does my app know who the user is」时触发——只要应用要托管到平台、又要用到身份或数据库，
  即使没点名平台也应触发。纯粹打包部署（不碰身份、不碰数据库）用「部署纳管」技能即可。
metadata:
  display-name: 平台能力接线（访问者身份 / 应用数据库 / 模型）
---

# 平台能力接线

你的任务：让应用**用平台给的东西**，而不是自己造一套。平台已经替应用做了登录、做了数据库、做了本地
运行环境；应用只需要**读注入的头**和**读注入的环境变量**。本文件每一章都是「照做」而不是「参考」。

先读完目录再动手，**读的顺序就是目录的顺序**——第 1 章排在最前面不是偶然，它是唯一一个
「写错了应用照样跑起来、只是身份是错的」的地方。

1. [访问者身份](#1-访问者身份先读这一章) —— 有一个静默失败点，先读
2. [应用数据库](#2-应用数据库)
3. [平台模型](#3-平台模型暂未提供) —— 暂未提供
4. [本地运行：`bisheng dev`](#4-本地运行bisheng-dev)
5. [自检清单](#5-自检清单)

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
| `X-BiSheng-Access-Token` | 每请求的短时访问凭据句柄 | **本轮没有消费方，不要依赖它做任何判断**；SDK 用法随后续版本补齐 |
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

### SDK 用法（随后续版本补齐）

平台 SDK 的 `auth`（一行拿到访问者对象）、`retrieve`（按访问者过滤的检索）、`storage`（附件存取）三件套
**随后续版本交付**，届时本章会补齐用法；在那之前，**读头**就是全部，而且 SDK 上线后读头的写法依然成立。

---

## 2. 应用数据库

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

## 3. 平台模型（暂未提供）

> **暂未提供。** 平台的「模型协议面」（让应用用 OpenAI 兼容客户端直接调平台管理的模型）
> **尚未上线**，本章随其一起补齐。在那之前：
> - **不要猜** base URL、不要拼 `BISHENG_PLATFORM_API_BASE + "/v1"` 之类的路径去试——那个变量是
>   **平台地址**，不是模型端点，现在没有任何模型端点在它下面。
> - 现在就需要调模型的应用：用应用**自己**的模型配置（地址、密钥都走环境变量引用，**不写进代码或清单**，
>   否则密钥扫描会拦），等平台面上线后再切换到平台注入的地址与凭据，届时模型名即模型管理里的原名、无档位转换。

---

## 4. 本地运行：`bisheng dev`

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

## 5. 自检清单

动手写代码前后各对一遍：

- [ ] 没有登录页、没有密码校验、没有自签 token；身份只从 `X-BiSheng-User-Id` 等请求头读。
- [ ] `X-BiSheng-User-Name` / `Dept-*` 显示前做了 `unquote`；缺 `Dept-*` 头当「没有部门」处理，不是报错。
- [ ] 用户数据表带 `user_id`，查询恒带 `WHERE user_id = ?`。
- [ ] 数据库路径读 `BISHENG_APP_DB_PATH`（或 `_URL`），没有写死；建表 `IF NOT EXISTS`；加列走 `ensure_column`。
- [ ] 没有改列/删列；真要做，走「加新列 → 双写 → 下个版本清理」并带 `--confirm-schema-change`。
- [ ] 没有拼任何模型端点地址；模型密钥只以环境变量引用出现。
- [ ] `bisheng dev` 起来后，通过**本地入口地址**访问，页面上显示的是你的服务账号名。

跑一次连通自检：`python selfcheck.py`（未 login / 平台不可达 时给出可读原因；在 `bisheng dev` 起的进程里跑还会检查数据库变量）。

---

## 参考

- `example/` —— 零依赖、可直接 `bisheng dev` / `bisheng deploy` 的最小样例：读身份头显示「你是谁」，
  按人存便签到应用数据库，含一次幂等加列。**改造它比从零写更稳**。
- `selfcheck.py` —— 连通自检（登录态 + 平台可达 + 库变量可用）。
- 「部署纳管」技能（`deploy-hosting`）—— 打包、清单、预检排障；本包假定你已经读过它的四条铁律。
