---
name: deploy-hosting
description: >-
  把本地写好的一个应用（网页、表单、看板、小工具、后端服务……用任意语言/框架写的）
  部署、发布、上线到公司/企业/内部的「应用平台」，让同事能在应用广场/应用中心里点开用时使用。
  当用户说到「部署到公司的应用平台」「发布这个应用给全公司用」「上线到内部平台」「让别人能访问我做的这个东西」
  「deploy this to our platform」「把它挂到应用广场」，或在用 bisheng 命令行（bisheng deploy / bisheng login）
  部署一个带 bisheng-app.yaml 的项目时触发——即使没点名具体平台名字也应触发。
  本技能给出托管运行契约（应用必须遵守的几条约定，否则本地跑得好、平台上起不来）、
  应用清单 bisheng-app.yaml 的写法、部署工作流与预检排障、以及部署前自检清单。
  纯粹本地开发、不打算部署上线的，不需要本技能。
metadata:
  display-name: 部署纳管（把本地应用发布到企业应用平台）
---

# 把本地应用部署到企业应用平台

你的任务：帮用户把一个**本地能跑起来的应用**部署到公司的应用平台，上线后同事能在应用广场里点开用。
平台负责托管——打包、构建镜像、拉起容器、路由、身份注入都由平台做；**你只要让应用遵守一份很小的运行契约，
并写对一张应用清单**。下面每条都照做，不要试探。

平台侧的命令行工具叫 `bisheng`（`login` / `deploy` / `logs` / `skills sync`）。目标平台由 `bisheng login`
时用的地址和凭据决定，不写死在代码里。

## 0. 先读完再动手

这一轮**先把本文件读完**（必要时读 `example/` 里的可运行样例），下一轮再开始写代码。
边读边并行改文件，等于没读。核心就三件事,按顺序:**① 让应用满足运行契约(§1) → ② 写对清单(§2) → ③ 自检后 `bisheng deploy`(§4/§5)**。

---

## 1. 托管运行契约(照做,四条铁律)

应用跑在一个受限容器里。**每一条契约在本地 `python main.py` 时都恰好是无害的默认值**——所以同一份代码、
同一条路径,本地验过的行为在平台上成立,差别只在环境变量取值。违反任意一条,本地好好的、平台上会起不来
或行为跑偏,而且往往**日志干干净净、最难查**。

| 铁律 | 怎么做 | 违反的后果 |
|---|---|---|
| **① 监听平台注入的端口** | 读环境变量 `PORT`(等价 `BISHENG_APP_PORT`),别写死 | 硬编码端口 → 健康探针连不上,永远卡在「启动中」 |
| **② 绑 `0.0.0.0`,不是 `127.0.0.1`** | 服务绑 `0.0.0.0` | 绑 `127.0.0.1` 在容器里只有进程自己连得上,探针一直失败**而日志没有任何错误**——最难诊断的一种「起来了但不健康」 |
| **③ 只往 `/data` 写** | 数据库/缓存/上传文件一律写 `/data` 下 | 根文件系统**只读**,往别处写会在**运行期**才炸(不是构建期);另有 `/tmp` 是小容量临时卷 |
| **④ 对外链接带上 `BISHENG_APP_BASE_PATH`** | 见下方专节 | 平台把应用挂在 `/apps/{slug}` 下,链接漏前缀会跳到平台根路径 |

**平台注入、应用不可覆盖的环境变量**(前缀 `PORT` / `BISHENG_APP_` / `BISHENG_PLATFORM_` 都是平台保留的):

| 变量 | 含义 | 本地默认 |
|---|---|---|
| `PORT` / `BISHENG_APP_PORT` | 必须监听的端口(两者相等) | 自己给个默认如 8080 |
| `BISHENG_APP_BASE_PATH` | 对外基路径,如 `/apps/my-app` | 空串(= 根路径) |
| `BISHENG_APP_DB_URL` | 应用数据库连接串,如 `sqlite:////data/app.db` | 自己给个 `/data` 或本地路径 |
| `BISHENG_APP_DB_PATH` | 数据库文件路径,如 `/data/app.db` | 同上 |
| `BISHENG_APP_HEALTH_PATH` | 健康探测路径(默认 `/`) | `/` |
| `BISHENG_APP_ID` / `BISHENG_APP_SLUG` / `BISHENG_APP_VERSION` | 平台侧标识 | 可不用 |
| `BISHENG_PLATFORM_API_BASE` | 平台 API 基址(调用平台能力时用) | 可不用 |

读法永远是「读环境变量,取不到用本地默认」,例如:
`PORT = int(os.environ.get("PORT") or os.environ.get("BISHENG_APP_PORT") or 8080)`。

### 关于 ④ 基路径(BASE_PATH)——最容易踩、要单独讲清

平台把每个应用挂在 `/apps/{slug}` 下,前置代理(app-proxy)会**把这个前缀剥掉再转发**给应用。所以:

- 应用**收到的**请求路径是**根路径**(`/`、`/submit`……)——你按根路径写路由即可,不用自己拼前缀去匹配。
- 但应用**发出的**每一个链接、表单 `action`、跳转、静态资源引用,**必须自己带上 `BISHENG_APP_BASE_PATH` 前缀**,
  否则用户点一下就跳到平台根路径去了。本地这个变量是空串,拼出来正好是原样,所以本地看不出问题。

  统一写一个拼接函数,所有对外 URL 都过它:
  ```python
  BASE_PATH = (os.environ.get("BISHENG_APP_BASE_PATH") or "").rstrip("/")
  def url(path): return f"{BASE_PATH}{path}"   # 用 url("/submit") 而不是直接写 "/submit"
  ```

- **主流框架有现成开关,入口脚本已自动设好**,你只要用框架的相对路径能力,不用手拼:
  - FastAPI/uvicorn:`UVICORN_ROOT_PATH` 已注入 → uvicorn 自动处理;模板里用 `request.url_for(...)` 或 `{{ request.scope.root_path }}`。
  - Streamlit:`STREAMLIT_SERVER_BASE_URL_PATH` 已注入。
  - Gradio:`GRADIO_ROOT_PATH` 已注入。
- ⚠️ **但根绝对路径仍会 404**:手写的 `<img src="/logo.png">`、`fetch("/api/x")`、`redirect("/next")` 这类
  **以 `/` 开头的绝对路径**,平台**不会**帮你改写 HTML,预检也**不会**报错——它只是在浏览器里 404。
  要么用上面的 `url()` 前缀,要么用相对路径(`logo.png`、`api/x`)。

### 运行时其它事实

- ⚠️ **本版不支持 WebSocket**——这是唯一一条会让**一整类应用**上线即报废的限制,**动手写代码之前就要定型**。
  托管入口本版不反代 WS(反代能力在后续波次),握手会被**当场关闭**,close code `4501`。症状极具迷惑性:
  **不是 502**,前置 nginx 是通的、请求确实到了入口;应用自己的 JS 只收到一个 `close` 事件,
  **平台侧日志干干净净**——本地 `ws://localhost` 连得上,线上一定连不上,而且没有任何东西提示你为什么。
  凡是要服务端推送的场景(聊天、进度条、实时看板、协同编辑、`socket.io`/Gradio 的实时通道),
  **一开始就用 SSE(`text/event-stream`)或轮询实现**,别等上线才发现要重写。SSE 走普通 HTTP、入口原样透传流式响应;
  长连接**每几分钟发一次心跳**(入口上游读超时 600s,静默超过就会被断开)。
  清单里也不要写 `websocket:` / `ws_path:` 这类键——预检会以 **16232** 当场拒绝,换个键名不会让它变得可用。
- **运行环境三选一**:`python3.11`(Python 服务)/ `node20`(Node.js 服务)/ `static`(纯静态页面,平台用 nginx 托管)。
  不确定目标平台装了哪几个时,以 `bisheng deploy` 预检回的 16222 提示为准——它会列出本环境实际支持的取值。
- **健康检查探 `/`**:确保应用在 `/`(或 `BISHENG_APP_HEALTH_PATH`)返回 2xx,否则一直判不健康。
- **启动命令解析顺序**(最显式优先;清单里**没有**启动命令字段):
  - `python3.11`:环境变量 `BISHENG_APP_START` → 项目根 `Procfile` 里的 `web:` 行 → `main.py` → `app.py`。多数情况把入口写成 `main.py` 即可。
  - `node20`:`BISHENG_APP_START` → `Procfile` 的 `web:` 行 → `package.json` 的 `scripts.start` → `package.json` 的 `main` →
    `server.js` / `index.js` / `app.js` / `main.js`。`scripts.start` 里的命令会被直接执行(`node_modules/.bin` 已在 PATH 上),
    **不经过 `npm start`**;`BASE_PATH` 与 `BISHENG_APP_BASE_PATH` 同值,给框架用。有 `scripts.build` 时平台在构建镜像时先跑一次 `npm run build`
    (装齐 devDependencies 再裁掉),没有就只装 `dependencies`;有 `package-lock.json`(或 `npm-shrinkwrap.json`)用 `npm ci`,没有用 `npm install`。
  - `static`:没有进程可启动,以上都不看。平台找 `index.html`:先看包根目录,再看 `dist/`、`build/`、`public/`,取第一个命中的目录整个托管;
    未知路径回落到 `index.html`(前端路由可用),带扩展名的资源找不到就是 404。
- **依赖**:能只用标准库就别加依赖。`requirements.txt` 留空(node20 则 `package.json` 没有 `dependencies`)是合法且推荐的——
  构建就不需要联网拉包;在内网/信创环境「构建卡在拉不到包」是最常见、也最容易被误判成平台故障的失败。真要装,确认构建环境能联网。
  `node_modules/` 永远不会被打进包里;`dist/`、`build/` **默认也不打包**——`static` 应用要发构建产物时在 `.bishengignore` 里加一行 `!dist/`
  (或直接把 `index.html` 放在包根目录)。

---

## 2. 应用清单 `bisheng-app.yaml`

放在项目根,是 `bisheng deploy` 读的**唯一**配置文件。它由平台严格校验,**未知字段会当场报错(不是忽略)**——
写错键名会明确告诉你「did you mean …」。最小可用清单:

```yaml
manifest_version: 1          # 兼容性版本,填 1
name: 我的应用                # 必填,1-64 字
runtime: python3.11          # 必填,python3.11 / node20 / static 三选一
port: 8080                   # 必填,应用监听的端口
# 下面都是可选:
# description: 一句话说明      # ≤500 字
# slug: my-app               # 只能小写字母/数字/连字符;全局唯一;不填平台自动生成
# icon: icon.png             # 包内相对路径,PNG/JPG,≤1MB
# tier: light                # 资源档位,不填 = 轻量
```

**字段红线(容易踩):**
- 必填三项:`name` / `runtime` / `port`。缺一个都部署不了。
- **没有 `health` / `command` / `entry` / `start` 这些字段**——清单里写它们会因「未知字段」被拒。健康检查、
  启动命令都不在清单里配(启动命令见 §1 的解析顺序)。
- `capabilities:`(声明要调用的平台模型/知识库)由另一份技能覆盖:**平台能力接线**(`platform-wiring`)
  的「知识库检索」一章讲怎么声明、怎么以当前访问者的身份检索;本包只管交付,不讲接线。
  (部署到未开放能力位的环境时非空声明会被拒,错误码 16231——那一章也写明了。)
- `database.tables:` 可以声明,但**本轮平台不替你建表**——你自己在应用里用 `BISHENG_APP_DB_URL` 连库、
  `CREATE TABLE IF NOT EXISTS` 建表。声明了就会被**逐版本对比**:迭代发布时相对在线版本**删表 / 删列 / 改列**
  (类型、可空、默认值任一变化)都算破坏性变更,平台会拒(错误码 16229)并要求显式确认——终端上 `bisheng deploy`
  会打印变更清单后问你;非终端或脚本里要先看清清单、确认后带 `--confirm-schema-change` 重发同一个包。
  只加表 / 加列不用确认。**没有终端不等于默认同意**,不要为了跳过提问而无脑加这个 flag。
- `egress.domains:`(出站域名白名单)本轮只做格式检查,不做拦截。

---

## 3. 安全红线

平台托管应用天然处在企业内网、由平台管身份与网络,所以:

- **不要在应用里自建鉴权/登录页、不要硬编码密钥、不要硬编码数据库连接串**。
- 需要密钥/凭据时,**用环境变量引用**(`os.environ[...]`),不要把明文写进代码或清单;
  清单里出现疑似密钥会被密钥扫描拦下(错误码 16230/16241)。
- 数据库连接用平台注入的 `BISHENG_APP_DB_URL` / `BISHENG_APP_DB_PATH`,不要自己写死连接串。
- (用户身份、检索、附件存储等「平台能力接线」由另一份技能覆盖,本轮不展开。)

---

## 4. 部署工作流

**先确保 `bisheng` 命令可用**——你可能在一个**新会话**里跑,而命令行是上一次会话装的。若 `bisheng: command not found`(常报成"没有配置 bisheng CLI"),不是没装,多半是**装进了项目局部 venv 或没进 PATH**:
先在常见位置找 `~/.local/bin/bisheng`、`~/.bisheng-venv/bin/bisheng`、pipx 目录、项目 `./.venv/bin/bisheng`;找到就用它、并软链进 PATH(`mkdir -p ~/.local/bin && ln -sf <找到的路径> ~/.local/bin/bisheng`)。都没有就用 `pipx install` 重装(别装进项目 venv),判据是 `bash -lc 'bisheng --version'` 在全新 shell 里能跑通。

```bash
# 0. 若还没登录:管理员给你一把服务账号密钥(bs-sak-…),登录一次(凭据存本机,后面不用再输)
bisheng login <平台地址> --api-key bs-sak-...      # 或 --api-key-stdin 从标准输入读

# 1. 在项目根(有 bisheng-app.yaml 的目录)一键部署
bisheng deploy .

# 2. 想先本地看要打包哪些文件、不真的上传:
bisheng deploy . --dry-run

# 3. 看部署/运行日志排障:
bisheng logs
```

`bisheng deploy` 会依次做:**打包 → 上传 → 密钥扫描 → 托管预检(构建镜像 + 启动探活)→ 生成发布审批单**。
你不用管中间那些活儿。部署成功不等于上线——要等管理员在审批中心通过,应用才真正上线,入口是
`<平台地址>/apps/{slug}`。上线也不等于公开,授权给部门/用户组是平台界面上的另一步(不在 CLI 里做)。

**审批状态在终端里跟,别把开发者支去网页上刷:**

```bash
# 部署完一直等到终态再返回(审批 + 上线结果都等)
bisheng deploy . --wait               # --wait-timeout 秒数,默认 1800
```

`--wait` 按终态给不同退出码,你据此决定下一步,不用解析文案:

| 退出码 | 终态 | 下一步 |
|---|---|---|
| 0 | 通过并上线 | 输出里有入口地址,把它交给开发者 |
| 20 | 驳回 | 输出含驳回理由全文,照着改再 `deploy` |
| 21 | 撤回 | 提交人自己撤了,确认后重发 |
| 22 | 待上线 | 审批已过但上线没成:容量不足或上线执行失败。输出里的成因照抄给开发者,等资源或让 owner 在应用详情页手动上线,**不用重新审批** |
| 23 | 等待超时 | **不代表审批失败**,只是还没人审;稍后再查状态 |
| 24 | 审批单已取消 | 目标应用被删了,这一单**永远不会有结论**。重新 `deploy` 建新应用前,先删掉 `.bisheng/app.json` 里的过期标识 |
| 25 | 审批异常 | 平台没解析出审批人,这一单**永远不会有结论**。让开发者联系平台管理员处理异常单——改代码或重新发布都不会让它继续 |

已经 `deploy` 过、只想随时看一眼的,用 MCP 工具 **`bisheng_app_status`**(密钥需带 `app:manage` 位):
它返回应用的运行态和最近一次发布的审批结果,驳回时含理由全文。

`bisheng logs` 看的是应用自己的运行日志,**不是**审批状态,两者别混——应用还没上线时它自然没有输出。

**预检失败排障(常见错误码):**

| 码 | 含义 | 怎么修 |
|---|---|---|
| 16221 | 清单格式非法 | 按报错的字段名改;注意未知字段/缺必填 |
| 16222 | runtime 不支持 | 改成报错里列出的取值之一(`python3.11` / `node20` / `static`,以该环境实际装了哪些为准) |
| 16228 | 启动探活失败 | 十有八九是铁律 ①②:没读 `PORT`、或绑了 `127.0.0.1`;也可能应用 `/` 不返回 2xx |
| 16230 / 16241 | 清单里有密钥 / 源码里扫到密钥 | 移除明文密钥,改环境变量引用 |
| 16229 | 表结构变更未确认(相对在线版本删表 / 删列 / 改列) | 看清 CLI 打印的变更清单;确认影响后在终端回答「是」,或带 `--confirm-schema-change` 重发同一个包 |
| 16231 | capabilities 非空 | 本轮删掉 `capabilities:` |
| 16232 | 清单里声明了 WebSocket | 本版入口不反代 WS(握手关闭,close `4501`);删掉该键,推送改用 SSE / 轮询 |
| 16226 | 平台容量不足 | 稍后重试或联系管理员;审批已过时可用「手动上线」重试,无需重新审批 |

---

## 5. 部署前自检清单

`bisheng deploy` 前,对照逐条确认(这些正是本地能跑、平台起不来的高发原因):

- [ ] 端口读的是 `PORT`/`BISHENG_APP_PORT` 环境变量,没有写死。
- [ ] 服务绑的是 `0.0.0.0`,不是 `127.0.0.1`。
- [ ] 需要写文件的地方(数据库/缓存/上传)都写在 `/data` 下;数据库连接用 `BISHENG_APP_DB_URL`/`BISHENG_APP_DB_PATH`。
- [ ] 对外链接/表单 action/跳转/静态资源都带了 `BISHENG_APP_BASE_PATH`,或用框架相对路径;没有手写 `/开头` 的根绝对路径。
- [ ] 应用在 `/` 返回 2xx(健康检查过得去)。
- [ ] **没有用 WebSocket**(本版握手会被关闭);需要服务端推送的地方用的是 SSE 或轮询。
- [ ] `bisheng-app.yaml` 有 `name`/`runtime`(`python3.11` / `node20` / `static` 之一)/`port`;没有 `health`/`command` 等未知字段;`capabilities` 为空。
- [ ] 没有硬编码密钥/连接串/自建登录页。
- [ ] 依赖尽量少;`requirements.txt`(或 `package.json` 的 `dependencies`)里没有的包不要 import;纯标准库时留空。
- [ ] `static` 应用:`index.html` 在包根目录,或已在 `.bishengignore` 里 `!dist/` 取回构建产物。

跑一次连通自检脚本确认环境就绪:`python selfcheck.py`(未 login / 平台不可达 时会给出可读原因)。

---

## 参考

- `example/` —— 一个零依赖、直接可 `bisheng deploy` 的最小可运行样例(`main.py` + `bisheng-app.yaml`),
  四条铁律都在里面。**改造它比从零写更稳**。
- `selfcheck.py` —— 部署前连通自检。
- 平台仓库里 `examples/apps/form-survey` 是一个更完整的样例(表单 + SQLite 落库 + 统计),同一套契约。
