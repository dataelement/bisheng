# 对象存储浏览器路径设计

**版本**：v3.1.0-beta1。**更新**：2026-11-11。**状态**：2026-11-11 用户已确认。T001–T008 已做。页面验收仍待有入口和对象样本的环境。

关联：[已确认规格](./spec.md) · [版本契约](../release-contract.md)。本文是实现前的目标设计。规格正文已由用户确认维持现稿，本文不改 AC。

## 1. 目标与非目标

浏览器取对象时走固定前缀 `/object/{桶名}/{对象键}`。站点入口只放行当前公共桶和临时桶，配置里不写桶名。新地址由签发产生；已经存进库的旧路径在读出时改写，原文不改。

不搬迁对象，不改带对象存储公开主机名的服务端拉取，不处理签名主机名和浏览器主机名不一致，不把 `/assets/` 静态文件算进对象路径。

## 2. 约束

遵循 `docs/constitution.md` C1–C7。本特性不新增领域对象，不改知识库文件、消息、用户、工作流和应用附件的写入权。

特有约束：

- 对象存储校验的签名覆盖路径 `/{桶名}/{对象键}` 和查询串。入口去掉 `/object` 前缀后必须把其余路径和查询串原样交过去。
- 预签名的默认行为是剥掉主机名、交给浏览器。私有桶一旦也能从这条前缀到达，这个默认值就会变成可下载地址。
- 客户端页面挂在 `/workspace` 下，浏览器实际请求是 `/workspace/object/...`。管理端页面在站点根上，请求是 `/object/...`。两条都要到达对象存储。
- Compose 把宿主机的 `docker/nginx/conf.d` 挂进前端容器，镜像里的入口配置不会被这份部署加载。Helm 使用自己的配置清单，并且有两个 server。三处都要改同一种 location，只改镜像文件对 Compose 无效。
- 桶名判定不可用时不返回对象内容（AC-11）。判定接口不能要求登录：子请求若被登录拦截，所有图片都会失败。
- 路由路径不得包含 `config`。客户 WAF 会在进入服务之前拦截。

## 3. 设计决策

### 3.1 固定前缀，而不是按桶名生成入口配置

- 选定：浏览器路径为 `/object/{桶名}/{对象键}`。入口用两条前缀 location：`/object/` 和 `/workspace/object/`。用一次 rewrite 去掉可选的 `/workspace` 和固定的 `object/`，再转给对象存储。location 文本不包含桶名。
- 否决：用公共桶和临时桶的名字渲染 location。渲染结果仍是入口配置，换桶就要重新发布配置，与 AC-02 相反。
- 否决：用正则匹配任意第一段路径并转给对象存储。普通前缀 `location /` 低于正则，`/build`、`/login` 一类前端路由会被抢走。
- 否决：在入口里永久留下 `bisheng` 和 `tmp-dir` 两条兼容 location。已经改过桶名的环境对不上；配置里也仍然写着桶名。
- 原因：规格要求换桶不改入口配置，同时 MinIO 收到的路径必须仍是签名时的 `/{桶名}/{对象键}`。
- 重审条件：对象存储不再使用路径式地址，或者浏览器地址被要求完全不出现桶名。后者是规格里的方案 B，要先改 AC。

### 3.2 入口转发前判定桶名，签发时同时拒绝

- 选定：转发前发内部子请求。后端只对当前 `public_bucket` 和 `tmp_bucket` 返回 204，其它名字、空名字和判定失败都是拒绝，入口因此不把请求交给对象存储。`get_share_link` 在 `clear_host=True` 时若桶不是这两个，拒绝签发，不把打不开的地址交给浏览器。`clear_host=False` 保持完整主机名，不走这条浏览器路径。
- 否决：只靠签发约定，入口放行 `/object/` 下任意桶。`get_share_link` 的默认就是 `clear_host=True`。今天这个默认值签出的私有桶地址因为入口没有对应 location 而打不开；前缀放宽后，同一行调用会变成可下载地址。
- 否决：每个对象都先由业务接口读出字节再转发。知识库切片图现在是浏览器直连，范围比本特性要解决的换桶问题大。
- 原因：私有桶 `bisheng-apps` 的隔离目前靠「入口没有它的 location」（`src/runtime-manager/runtime_manager/storage.py` 中的 pit 20）。固定前缀必须用另一次判定补上这道墙。AC-03、AC-04、AC-11 分别要求拒绝读取、拒绝签发、判定失败时不返回内容。
- 重审条件：图片页的额外往返被测成不可接受，且私有桶已有不会被默认签发绕过的别的隔离。

### 3.3 读出时改写，不改已存原文

- 选定：数据库、消息正文和知识库切片原文保持不变。交给浏览器之前，把第一段等于当前公共桶或临时桶的路径改成 `/object/{同一桶}/...`。解析同时接受旧形式和新形式。新签发的地址直接是新形式。
- 否决：上线时改写 `chatmessage` 和向量库里的历史文本。这些正文里还有普通句子，批量替换桶名会误伤，也覆盖不了规格明确不改的原文要求（AC-05）。
- 否决：只改新签发、不改读出。上线当天入口不再认识 `/{桶名}/...`，不换桶的环境也会打开 `index.html`。
- 原因：对象键存在 `knowledgefile.object_name` 等列里，浏览器路径是读的时候现签的。带桶名的旧路径嵌在 `chatmessage.message`、`chatmessage.files` 和切片 Markdown 里，不是单独的路径列。
- 重审条件：出现不经过接口读出、又必须继续打开的旧路径，例如浏览器长期缓存的完整 URL。那种地址在签名过期后本来也要重签。

### 3.4 不统一各部署的 Host 头

- 选定：新 location 复制该文件里现有对象存储 location 的 Host 处理，不在本特性里把三份配置改成同一种 Host。
- 否决：顺便把 Host 都设成 `sharepoint`，或都改成浏览器带来的 Host。Helm 现在把 Host 设成 `sharepoint`；Compose 的 `docker/nginx/conf.d/default.conf` 和镜像内的 `src/frontend/nginx.conf` 没有设。签名校验的是 Host，统一方式会让其中一种部署从成功变成 `403 SignatureDoesNotMatch`。
- 原因：规格明确不处理签名主机名和浏览器主机名不一致。
- 重审条件：单独处理公开主机名和签名 Host 的特性。

### 3.5 判定结果不在入口缓存

- 选定：每次对象请求都做桶名判定，入口不缓存 204 或拒绝。
- 否决：按桶名缓存几十秒。换桶并重启后端之后，缓存期内旧桶仍会被放行、新桶仍会被拒绝。
- 原因：判定只比较两个配置字符串，失败必须关闭（AC-11）。缓存把「配置已经生效」和「入口还记得旧答案」拆开。
- 重审条件：知识库正文页的图片把后端延迟测成页面不可用。那时只缓存「允许」的桶名，拒绝和失败仍然不缓存。

## 4. 现状与目标流程

### 4.1 今天

`MinioStorage.get_share_link` 默认 `clear_host=True`，用 `sharepoint` 签路径式地址，再由 `clear_minio_share_host` 剥掉主机，得到 `/{桶名}/{对象键}?X-Amz-...`。浏览器请求这个路径。入口用桶名匹配后转给对象存储。

知识库切片图不走签发。`knowledge/rag/pipeline/loader/base.py`、`knowledge/rag/pipeline/transformer/image_upload.py`、`api/services/etl4lm_loader.py`、`api/services/patch_130.py` 直接拼 `/{桶名}/knowledge/images/...`。匿名策略只覆盖公共桶的 `knowledge/images/*` 和 `tmp/images/*`。

解析旧路径时把第一段当桶名的位置：`workstation/api/endpoints/knowledge.py` 的 `_resolve_minio_object_from_filepath`，`core/storage/chat_attachment.py`，`knowledge/domain/services/temp_upload_service.py`，`workstation/domain/services/kb_image_stage.py`，`common/image_view/fetch.py`，`linsight/domain/services/workbench_impl.py`。

本地开发另有两份代理，同样写死 `bisheng` 和 `tmp-dir`：`src/frontend/client/vite.config.ts`，`src/frontend/platform/vite.config.mts` 的 `fileServiceRoutes`。平台两处 Markdown 把 `(bisheng/` 换成 `(/bisheng/`：`platform/src/pages/BuildPage/flow/FlowChat/MessageMarkDown.tsx`，`platform/src/pages/KnowledgePage/components/Markdown.tsx`。

`/assets/bisheng/` 是前端包里的静态文件，不是对象存储。

### 4.2 目标数据流

签发：调用方给出桶和对象键 → `get_share_link` 在要剥主机时先确认桶是当前公共桶或临时桶 → 签名仍覆盖 `/{桶名}/{对象键}` → `clear_minio_share_host` 剥掉主机后加上 `/object`。`clear_host=False` 的返回值不变。

直接拼出的切片图地址改为调用同一个浏览器路径函数，得到 `/object/{当前公共桶}/knowledge/images/...`。匿名策略仍由对象存储执行。

读出：返回给浏览器的消息正文、附件 JSON 和切片文本经过一个改写函数。它只改「路径第一段等于当前公共桶或临时桶」的出现，不改 `/assets/` 下的同名片段，不改库。

浏览器请求 `/object/...` 或 `/workspace/object/...` → 入口抽出桶名并做内部判定 → 204 之后 rewrite 成 `/{桶名}/{对象键}` 并原样转发查询串 → 对象存储校验签名或匿名策略。判定不是 204 时，入口不转发。

再次提交：解析函数接受 `/object/{桶}/{键}` 和 `/{桶}/{键}`。桶必须仍是当前两个桶之一，对象键再交给既有的存在性检查和业务权限。

本地开发的两份 Vite 代理只匹配 `/object` 和 `/workspace/object`，去掉前缀后转发到与 `sharepoint` 一致的对象存储地址。转发前调用同一个判定接口；判定失败则不转发。

### 4.3 对外可见的约定

| 项目 | 契约 |
|---|---|
| 浏览器路径 | `/object/{桶名}/{对象键}`，可带原有查询串。客户端页面前面还可以有 `/workspace` |
| 已存原文 | 不改。读出结果里，当前两个桶的旧路径变成上面的浏览器路径 |
| 再次提交 | 旧形式和新形式定位同一对象键 |
| `GET /api/v1/storage/browser-bucket` | 无登录。请求头 `X-Object-Bucket`。允许返回 204，不允许、空值或无法读取配置返回 403。响应无对象内容 |
| `get_share_link(..., clear_host=True)` | 桶不是当前两个桶时拒绝签发，不返回路径 |
| `get_share_link(..., clear_host=False)` | 仍返回带公开主机名的完整地址 |

不在本设计里预分配新的错误码号。实现时在对象存储既有错误码段取下一个未占用号，响应沿用现有错误信封。判定接口本身只用 204 和 403。

### 4.4 模块边界

| 模块 | 负责 | 不做什么 |
|---|---|---|
| `core/storage/minio/minio_storage.py` | 签发前拒绝非当前两个桶的浏览器地址；剥主机后加 `/object` | 不改 `clear_host=False`；不判定业务下载权限 |
| 新的路径函数，放在存储层，供签发、拼图、读出改写和解析共用 | 生成浏览器路径、改写文本、从两种形式解析出桶和对象键 | 不访问数据库，不搬迁对象 |
| 存储 API 的判定端点 | 读当前两个桶名并返回 204 或 403 | 不接收登录用户，不返回对象字节，路径中不出现 `config` |
| `docker/nginx/conf.d/default.conf`、`src/frontend/nginx.conf`、`docker/helm/bisheng/templates/configmap-nginx.yaml` 的两个 server | 各增加 `/object/` 与 `/workspace/object/`，删除按桶名匹配的 location；Host 处理复制本文件现有对象存储 location | 不把三份 Host 策略改成同一种；不代理任意第一段路径 |
| 两份 Vite 配置 | 开发代理改为固定前缀，并在转发前调用判定接口 | 不在配置里写桶名 |
| 两处平台 Markdown 替换 | 不再假设公共桶的字面量是 `bisheng` | 不代替后端读出改写 |
| 上列解析调用点 | 改为共用解析函数 | 不各自再写一套桶名分割 |

业务权限仍在现有的下载、预览和查看入口上判断。桶名判定只回答「这个桶能不能从浏览器这条路径到达」。

## 5. 已知坑

| # | 事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `get_share_link` 默认 `clear_host=True` | 私有桶会被签成浏览器地址；前缀放行后即可下载 | 签发前拒绝非当前两个桶 |
| 2 | 签名路径不含 `/object`，Host 随部署文件而不同 | 改写路径或顺手统一 Host 会得到 `SignatureDoesNotMatch` | rewrite 只去掉前缀；Host 复制本文件现有 location |
| 3 | Compose 挂载 `docker/nginx/conf.d`，盖住镜像内的 `src/frontend/nginx.conf` | 只改镜像配置时，Compose 环境仍走旧桶名 location | 三份入口配置一起改 |
| 4 | 客户端实际请求带 `/workspace` | 只匹配 `/object/` 时，工作台图片全部落到 SPA 的 `index.html` | 同时匹配 `/workspace/object/`，rewrite 先去掉 `/workspace` |
| 5 | 静态资源路径是 `/assets/bisheng/...` | 读出替换把站点 logo 改到对象存储，图片损坏 | 改写只认路径第一段是当前桶名，不认 `/assets/` 后面的片段 |
| 6 | 判定子请求若带上页面的登录头，或端点要求登录 | 子请求 401，入口把所有对象都拒绝 | 端点不要求登录；子请求清掉 `Authorization` 和 `Cookie` |
| 7 | 命名 location 里的 `proxy_pass` 不能带 URI | 判定 location 写成 `proxy_pass http://backend/api/...` 时整站入口起不来。现有 `@apps_unavailable` 已因此失败过 | 用 rewrite 设定判定路径，`proxy_pass` 只写上游 |
| 8 | `default.conf` 里现有正则 `^(/workspace)?/bisheng\|/tmp-dir` 的 `\|` 没有把 `/tmp-dir` 锚在开头 | 照抄这条正则会让路径中间出现 `tmp-dir` 的请求也被转发 | 删除该 location，不用它做模板 |
| 9 | 本地代理的 Host 必须与后端 `sharepoint` 字面一致，`localhost` 和 `127.0.0.1` 是不同签名 | 开发环境对象请求 403，看起来像桶名改错 | Vite 继续使用现有的 MinIO 代理目标和 Host 告警 |

## 6. 契约与依赖

### 6.1 提供给其它模块

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `/object/{桶}/{对象键}` 与 `/workspace/object/{桶}/{对象键}` | 浏览器 URL | 管理端、客户端、本地开发代理 |
| 浏览器路径的生成、文本改写、两种形式的解析 | 存储层函数 | 签发、切片图拼路径、消息和切片的读出、再次提交的解析 |
| `GET /api/v1/storage/browser-bucket` | 内部 HTTP，204 或 403 | 站点入口的子请求，以及两份 Vite 开发代理 |

### 6.2 依赖

| 依赖 | 形式 | 风险 |
|---|---|---|
| `object_storage.minio.public_bucket` 与 `tmp_bucket` | 进程启动时读入的配置 | 改配置后未重启签发进程和判定进程，新旧桶名会不一致 |
| 对象存储的签名和匿名策略 | 转发后的 GetObject | 前缀或查询串被改掉则签名失败；匿名范围仍只在对象存储侧 |
| 现有下载和预览的业务权限 | 签发和解析之前的既有检查 | 若把桶名判定当成业务权限，公共桶里未签名的非匿名对象会被误当成已授权 |
| `sharepoint` | 签名时的主机名 | 本特性不改它。它和浏览器主机不一致时，失败方式与今天相同 |
| 客户端 `/workspace` 前缀、管理端站点根 | 前端部署形态 | 只处理其中一条时，另一端的对象请求变成 HTML |

## 7. 测试与验证

单元测试覆盖路径函数：生成、两种形式解析、`/assets/bisheng/` 不被改写、非当前桶不改写、带查询串的签名路径只去掉前缀。签发测试覆盖当前两个桶可以签出 `/object/...`，其它桶在 `clear_host=True` 时被拒绝，`clear_host=False` 仍带主机名。判定端点测试覆盖允许、拒绝、空桶名、不要求登录。

入口配置用现有的配置检查确认三份文件都有两条新 location、都没有按桶名写的 location，且判定 location 的 `proxy_pass` 不带 URI。开发代理的匹配改为固定前缀，用现有前端测试里写死 `/bisheng/` 和 `/tmp-dir/` 的用例改成新路径后跑通。

手动验证需要一套已有公共桶和临时桶的环境：打开一条旧的知识库预览、一张切片图、一个会话附件和一个头像，确认请求路径以 `/object/` 开头且内容不是 `index.html`。再请求 `/object/` 加一个其它桶名，确认没有对象内容。不修改 Compose 挂载的入口文件就重启后端，不能算验证过 AC-02。

## 8. 不做的事

不统一三份入口的 Host。不缓存桶名判定。不改数据库和向量库里的历史文本。不搬迁对象。不把业务下载权限并进桶名判定。这些都有单独的重审条件，见 §3。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-11 | 初版 | 规格确认后编写，代码未改 |
| 2026-11-11 | 路径、签发、判定接口和入口配置已实现 | 按 tasks T001–T004、T006 落地；T005 与 T007 的判定仍待做 |
