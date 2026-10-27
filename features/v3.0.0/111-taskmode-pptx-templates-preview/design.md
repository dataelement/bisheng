# Design: 任务模式 PPT 内置模板与在线预览

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [discovery.md](./discovery.md)
**版本**: v3.0.0（发版线 `feat/3.0.0`）
**最后更新**: 2026-10-27（初版，待 ★ 确认）

---

## 1. 目标与非目标

- **目标**：
  - 把任务模式 PPT 的生成方式从"模型现场写坐标"改为"克隆模板原型页，再按插槽填内容"，并补齐容量、版面节奏、示例残留三类检查。
  - 让任务模式结果区能在线逐页查看 pptx 交付物。
- **非目标**：
  - 不引入新运行时：不加 Node，也不做 PPTD 编译器。
  - 不新增模型工具，继续走代码执行器加技能包脚本。
  - 不做模板选择界面和企业模板库。
  - 不改知识库的 pptx 预览。
  - 不改用户上传模板的生成路线。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C8。Constitution Check 结论：

- C1：新接口只调用服务层；转换、缓存、锁都在 domain service 里。
- C4：灵思会话不是 F048 资源类型（`permission/` 只登记了 `linsight_skill`），现有判定是"所有者、管理员、分享链接"。本功能沿用这套判定，不查询 OpenFGA，也不新增资源类型。
- C5：使用 11025，登记在 release-contract。
- C8：预览结果在 MinIO，锁在 Redis。

本功能特有的约束如下：

- **技能只能经代码执行器生效**。脚本必须 exit 0，结果用 stdout 表达；子进程用 `sys.executable` 启动；cwd 是工作区根。相关规则见 `builtin_skills/AGENTS.md`。E2B 执行器看不到 `skills/` 目录。
- **部署是纯文本环境**。平台默认的 dashscope 通道不收 base64 图片，因此模型选模板、做检查都不能依赖看图。
- **用户端字体不可知**。文件最终由用户机器上的 PowerPoint 或 WPS 渲染；服务器只有 `fonts-wqy-zenhei`（见 `base.Dockerfile:13`）。
- **pre-commit 限制单文件不超过 500KB**（`.pre-commit-config.yaml:13-14`，`src/backend/bisheng/**` 不在豁免列表里）。
- **多节点（C8）**。预览产物放 MinIO，单飞锁放 Redis；本地磁盘只存一次转换用的临时文件。
- **错误码**。灵思模块 110 段内取 **11025**。已在发版线和 vibe 两条线 grep 确认未占用；登记见 release-contract 的"已分配模块编码"。

---

## 3. 方案对比与选定

### 决策 1：模板的承载形式

- **备选**：
  - A. 用 python 版式函数（如 `layout_cards(prs, theme, ...)`）表达模板。代码即模板，便于参数化；缺点是设计师无法在 PowerPoint 里直接看和改，视觉调整全靠改代码。
  - B. 把带占位符的 slideLayout 放进母版。PowerPoint 原生支持；但卡片、指标、流程这类多元素结构要配大量占位符，python-pptx 又不能直接创建版式，维护成本高。
  - C. **原型页 pptx，加插槽清单**。模板就是一份普通 pptx，每页是一个原型版式，可编辑元素按约定命名。模型克隆原型页后按名字填写，生成脚本同时产出插槽清单（`layouts.json`）。
- **选定**：C。
- **原因**：
  - 原型页可以直接在 PowerPoint 里打开审阅，满足 AC-31 的签字要求。
  - 克隆整页能保留全部结构元素和样式。
  - 用户自建的 `soe-closeout-deck` 已在央国企结项材料上实证过"克隆原型页、按插槽名填写"这套做法。
  - 插槽清单给检查脚本提供容量和示例文字，使 AC-10、AC-11 可以实现。
- **何时该重新考虑**：进入第二期、引入声明式格式和编译器时，模板改由编译器输入表达。

### 决策 2：模板由生成脚本产出，不手工绘制

- **备选**：A. 在 PowerPoint 里手工做 5 份 pptx；B. 写开发期生成脚本，从主题令牌和版式几何库产出 pptx 与插槽清单。
- **选定**：B。脚本放在 `src/backend/scripts/pptx_templates/`，生成产物提交进仓库。
- **原因**：
  - 5 套模板共用 13 类版式，几何只需写一次。
  - 插槽容量由框尺寸和字号自动算出，不会和图形漂移。
  - 改配色或改版式只需重跑脚本。
  - 手工 pptx 的元素命名和容量要靠人维护，容易出错。
- **何时该重新考虑**：设计师要直接交付手绘模板时。此时保留插槽命名约定，改为用一个"校验加抽取清单"脚本替代生成脚本。

### 决策 3：主题色和字体同时写进主题 XML

- **选定**：生成脚本做两件事。
  - 把每套模板的配色写入主题 `accent1–6`、`dk1/lt1/dk2/lt2`，把中西文字体写入 `majorFont/minorFont` 的 `latin` 和 `ea`。
  - 原型页上的文字同样逐 run 写 `latin` 和 `ea`。
- **原因**：
  - 模型在模板上新增的文字、python-pptx 新建的原生图表，都会默认继承主题，不需要模型逐一设色设字体。
  - 只写主题会被 run 级属性覆盖，只写 run 又覆盖不到新元素，所以两处都写。
- **被否方案**：只在 run 上写字体。这样新加的图表、表格会回退到 Calibri 加宋体。
- **何时该重新考虑**：需要支持用户在 PowerPoint 里一键换主题配色，并且原型页改为全部使用主题色引用（`schemeClr`）时，可以去掉 run 级颜色。

### 决策 4：图表不随原型页克隆，改为按 `chart_area` 现放

- **备选**：A. 原型页里放原生图表，克隆后调用 `replace_data`；B. 原型页里放一个命名为 `chart_area` 的占位框，由 `Deck.chart()` 在该位置新建原生图表并删掉占位框。
- **选定**：B。
- **原因**：
  - 图表是独立 part。按 `soe-closeout-deck` 的克隆法，只会复制关系、共用同一个 part，结果是改一页的数据，另一页的图跟着变。若要深拷贝 chart part，需要自己处理 partname 和嵌入的 xlsx，风险高。
  - 新建图表的系列色能通过决策 3 自动取到主题色。
- **何时该重新考虑**：需要预置复杂组合图（例如桥图）时，再实现 chart part 深拷贝。

### 决策 5：新检查放在独立模块，按原型页做基线差分

- **选定**：
  - 新建 `scripts/deck_checks.py` 承载四项新检查，由 `inspect_deck.py` 调用并合并输出。
  - 当存在 `Deck.save()` 写出的 manifest 时，对每张输出页，先在对应原型页上跑同一批既有检查得到基线；输出页上"同检查项、同元素名"的发现视为模板自带，不报（AC-11）。
  - 没有 manifest 时（从零生成或用户模板路线）：容量检查和示例残留检查跳过；连续同版式检查改用构图轮廓判断；封面焦点检查照常执行。
- **原因**：
  - `builtin_skills/AGENTS.md:29` 要求有基线时报差值。
  - 不做差分的话，模板自带的结构线会撞上既有的"文字压装饰线"检查，产生大量误报，模型会学会无视检查。
  - `inspect_deck.py` 已有约 600 行，拆模块是为了可读性。
- **级别**：四项新检查都报 WARN，遵守 `AGENTS.md:25`。是否升为 ERROR，等 AC-30 的真实产物标定后再决定。
- **何时该重新考虑**：如果基线差分仍有误报（同名元素在填写后位置变化），改为按"原型页上的元素集合"整体豁免结构元素；如果第二期引入编译器，检查迁入编译器。

### 决策 6：pptx 预览采用"按需转换加对象存储缓存"，不在任务结束时预生成

- **备选**：
  - A. 任务结束时在 linsight worker 里统一转 PDF。缺点：每个任务都要多花几十秒，用户不看也要付这个成本；历史任务覆盖不到。
  - B. 打开时按需转换。结果写 MinIO，用 Redis 单飞锁保证同一文件只转一次；在 API 进程内用线程执行转换。
  - C. 投递 Celery 异步转换。会引入新队列路由，而现有同类按需转换（`download-md-to-pdf-or-docx`）都在请求内完成。
- **选定**：B。
- **原因**：
  - 用户只为自己看的文件付转换成本。
  - 历史任务也能预览（spec §3）。
  - 前端已有 `FilePreview` 把 pptx 路由到 PDF 查看器（`packages/file-viewers/src/formats.ts`），后端只需交付一个 PDF 地址。
- **代价与护栏**：
  - LibreOffice 转换占 CPU。每个 API 进程用 `asyncio.Semaphore(2)` 限制并发转换数。
  - 转换超时 120 秒，前端等待上限 90 秒。若超出 90 秒，下次打开会直接命中后端已完成的缓存。
- **何时该重新考虑**：如果转换让 API 进程的 CPU 长期打满，改为方案 C。

### 决策 7：预览接口的鉴权，与下载接口抽成同一个函数

- **选定**：
  - 把 `linsight_file_download` 里"会话所有者、管理员、两种分享形态"的判断，抽成服务函数 `LinsightArtifactPreviewService.load_accessible_version()`。下载和预览两个接口都调用它（AC-24）。
  - 预览接口另加一层文件归属校验：`file_url` 去掉桶前缀后，必须以 `linsight/final_result/{svid}/` 开头，不得含 `..`，扩展名只能是 `.ppt` 或 `.pptx`。
- **原因**：两处各写一份权限判断会漂移。灵思会话是所有者模型，没有接入 F048 资源授权，因此沿用现有判定，不新建 OpenFGA 资源类型。
- **被否方案**：照抄 `download-md-to-pdf-or-docx` 的写法。它不校验 `file_url` 的归属（见 §8）。
- **何时该重新考虑**：灵思会话接入 F048 资源授权（成为 `require_business_action` 的资源类型）时，`load_accessible_version` 改为调用统一授权运行时。

---

## 4. 系统现状（实现后的样子）

### 4.1 PPT 生成数据流

1. **种子化技能包**。启动时，`builtin_skill_seeder.py` 把 `bisheng-pptx`（含 `templates/**`，按字节读取）写进 MinIO 的技能包对象。
2. **物化到工作区**。任务开始时，`task_exec._provision_session_skills` 把技能文件物化到工作区 `skills/bisheng-pptx/`。
3. **模型选模板**。模型读 SKILL.md，运行 `list_templates.py` 得到模板和版式的文字目录。
4. **写大纲**。模型写 `scratch/outline.md`，每页一行：首读结论、`layout_id`、证据。
5. **写构建脚本**。模型写 `scratch/build_deck.py`，用 `deck_template.Deck` 依次 `add` 原型页、`fill` 插槽、放 `chart` / `table` / `image`，最后 `save` 到 `output/<名>.pptx`。`save` 会删除原型页，并写出 `scratch/<名>.manifest.json`。
6. **检查**。`inspect_deck.py output/<名>.pptx` 自动查找同名 manifest，合并既有检查与 `deck_checks` 的结果，输出带页码和元素名的发现。
7. **交付**。ERROR 清零后交付；原有的交付物上传逻辑（`linsight/domain/utils.py:get_final_result_file`）不变。

### 4.2 pptx 预览数据流

1. 结果区 `PreviewBody` 遇到 slides 类型的文件，调用 `getLinsightFilePreviewApi(file_url, versionId, shareToken)`。
2. 后端 `POST /api/v1/linsight/workbench/file_preview` 先用 `load_accessible_version` 鉴权，再校验文件归属，然后调用 `LinsightArtifactPreviewService.get_pptx_preview()`：
   - 缓存对象 `linsight/preview/{svid}/{file_id}.pdf` 已存在：返回 `{status: "ready", file_path}`。
   - 缓存不存在且抢到锁（`SET NX EX 180`）：从 MinIO 读原文件写入临时目录，在信号量内用线程运行 `convert_ppt_to_pdf`，再用 PyMuPDF 校验页数大于 0，然后 `put_object`、释放锁，返回 ready。
   - 没抢到锁：返回 `{status: "converting"}`。
   - 转换失败：抛出 `LinsightArtifactPreviewError(11025)`，释放锁，不写缓存。
3. 前端拿到 `converting` 时每 2 秒轮询一次，90 秒后放弃。拿到 ready 后渲染 `<FilePreview fileType="pptx" fileUrl={pdfUrl} compactMode />`，上方显示 AC-26 的提示。失败时走现有的"下载查看"兜底。

### 4.3 关键数据结构与约定

| 结构 | 格式 | 说明 | 消费者 |
|---|---|---|---|
| 插槽命名 | shape.name = `<slot>`，组内元素为 `<group>.<part>`（如 `card3.title`） | 由生成脚本写入；`drop("card3")` 删除整组 | `Deck`、`deck_checks` |
| `templates/catalog.json` | `{templates:[{id,name,scenes,palette,fonts,layout_count}]}` | 模板总目录 | `list_templates.py` |
| `templates/<id>/layouts.json` | `{id, layouts:[{layout_id, slide_index, family, use_for, slots:[{name, role, capacity, max_lines, sample}], groups:[...]}]}` | `role` 取值：`title`、`subtitle`、`body`、`caption`、`number`、`label`、`chart_area`、`table`、`image_area`；`capacity` 按字数计 | `Deck`、`deck_checks` |
| 字数口径 | 汉字或全角字符记 1，其余字符每 2 个记 1 | 容量与填写字数用同一口径 | 生成脚本、`Deck`、`deck_checks` |
| `scratch/<名>.manifest.json` | `{template, pages:[{index, layout_id, filled:{slot: chars}, over_capacity:[...]}]}` | `Deck.save` 写出 | `inspect_deck` |
| 预览接口入参 | `{file_url, session_version_id}` + 可选 `share-token` 头 | 与下载接口一致 | client |
| 预览接口出参 | `{status: "ready", file_path}` 或 `{status: "converting"}`；失败返回错误码 11025 | `file_path` 与下载接口同形态（去掉 host 的签名地址） | client |
| 预览缓存键 | `linsight/preview/{svid}/{file_id}.pdf`，主桶 | `file_id` 取原键文件名去掉扩展名 | 后端 |
| 单飞锁键 | `linsight:pptx_preview:{svid}:{file_id}`，过期 180 秒 | 转换结束（成功或失败）都会删除 | 后端 |

### 4.4 模板与版式

5 套模板的 id 分别是 `gov-red`、`blueprint`、`operating`、`tech-dark`、`classroom`，画布为 16:9（13.333 × 7.5 英寸）。

13 类共用版式的 `layout_id` 如下：

- `cover`、`agenda`、`section`、`statement`
- `two-column`、`cards-3`、`cards-4`、`kpi-4`
- `chart-insight`、`compare`、`process`、`timeline`、`table`、`closing`

其中 `cards-3` 和 `cards-4` 同属"卡片网格"一类，所以是 14 个 id、13 类版式。

各套的专属版式：

| 模板 | 专属版式 |
|---|---|
| `blueprint` | `architecture`（分层架构）、`risk-register`（风险登记） |
| `operating` | `scorecard`（计分表，突出异常行）、`bridge`（贡献对账） |
| `classroom` | `objectives`（学习目标）、`quiz`（自测） |
| `gov-red` | `honor-wall`（成果荣誉） |
| `tech-dark` | `feature-hero`（产品亮点大图） |

字体：中文用微软雅黑，`gov-red` 的标题用黑体；西文用 Arial。原型页只放矢量元素和示例文字，示例文字都标注"示例"。

### 4.5 关键模块职责

| 模块与文件 | 职责 | 不做什么 |
|---|---|---|
| `src/backend/scripts/pptx_templates/{themes,layouts,build_templates}.py` | 开发期产出 5 份 `template.pptx`、`layouts.json` 和 `catalog.json` | 不随技能包下发 |
| `bisheng-pptx/scripts/deck_template.py` | `Deck.open/add/fill/drop/table/chart/image/save`；克隆页面并改写 rId；填写时记录超容量；保存时删除原型页并写 manifest | 不做检查判定（交给 `deck_checks`） |
| `bisheng-pptx/scripts/deck_render.py` | 原生图表（含瀑布图）与表格的渲染，生成脚本和 `Deck` 共用 | 不读写模板清单 |
| `bisheng-pptx/scripts/list_templates.py` | 以纯文本列出模板、适用场景和版式表 | 不渲染图片 |
| `bisheng-pptx/scripts/deck_checks.py` | 实现四项新检查和基线差分 | 不打印"结论: 通过"（只有 `inspect_*` 可以打印） |
| `bisheng-pptx/scripts/inspect_deck.py` | 新增 `--manifest` 参数并能自动查找；合并输出 | 不改变既有检查的阈值 |
| `linsight/domain/services/artifact_preview_service.py` | 会话版本鉴权、文件归属校验、缓存、单飞锁、转换 | 不处理 HTTP 细节 |
| `linsight/api/endpoints/linsight.py` | 新增 `file_preview` 接口；`file_download` 改调 `load_accessible_version` | 不在接口层写业务判断 |
| `knowledge/.../libreoffice_converter.py` | `convert_ppt_to_pdf` 增加可选参数 `timeout`，默认值保持 180 | 不改既有调用方的行为 |
| client `Linsight/Artifacts/{artifactUtils.ts, useSlidesPreview.ts, PreviewBody.tsx}` | 新增 slides 类型、轮询 hook、渲染加提示 | 不改用户上传文件的预览方式 |

---

## 5. 已知坑与反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | python-pptx 不能复制整页。克隆后 rId 由库重新分配，必须改写形状里的 `r:embed` 和 `r:id` | 图片指向错位，或 PowerPoint 报文件损坏 | `Deck.add`（逻辑参考 `soe-closeout-deck/deckkit.py:103`） |
| 2 | 图表是独立 part，复制关系会让两页共用同一个 chart part | 改一页的数据，另一页跟着变 | 决策 4：图表用 `chart_area` 现放 |
| 3 | 删页必须同时 `drop_rel` 并移除 `sldId` | 文件提示"已损坏" | `Deck.save` |
| 4 | `run.font.name` 只写 `<a:latin>`，`<a:ea>` 必须紧跟其后 | 中文回退宋体；`ea` 位置不对时 PowerPoint 打不开文件 | 复用 `pptx_helpers.set_font` |
| 5 | `add_textbox()` 默认写 `spAutoFit` | 溢出检查形同虚设 | 生成脚本显式设为 `MSO_AUTO_SIZE.NONE` |
| 6 | 有 manifest 时不做基线差分，模板结构线会命中"文字压装饰线"检查 | 大量误报，模型学会无视检查 | 决策 5 |
| 7 | 执行器失败时丢弃 stdout | 非零退出会让检查报告整份消失 | 所有脚本 exit 0（已有静态守卫） |
| 8 | `convert_ppt_to_pdf` 失败时返回 `None` 或 `False`，只记 debug 日志 | 失败被当作成功，缓存了空结果 | 服务层判断返回值，并用 PyMuPDF 校验页数大于 0 |
| 9 | 服务器渲染只有文泉驿正黑 | 预览的字宽与 PowerPoint 不同，可能被误判为溢出 | AC-26 的提示；检查以字数容量为准，不依赖渲染 |
| 10 | 用户上传的文件在结果区固定按解析正文预览（`getArtifactPreviewKind`） | 误把上传的 pptx 也走转换 | slides 类型只作用于任务生成的文件 |
| 11 | 生成脚本每次输出的 zip 时间戳不同 | 每次重跑都产生二进制 diff | 只在模板确有变更时重跑并提交 |
| 12 | 管理端技能文件查看页按 UTF-8 解码 | `.pptx` 显示成乱码 | 已知限制，列入 §8 |
| 13 | 没有 manifest 时基线扣除不生效，模板自带的出血装饰、贴边页脚会直接报 ERROR/WARN | 任何从模板做的文稿只要清单丢了就"不通过" | 模板本身做到对既有检查零 ERROR/WARN（装饰收进画布、页脚留 30pt、页码段落声明字号），由 `test_template_matches_its_slot_manifest` 与原型页检查守住 |
| 14 | 页码是 `<a:fld>`，python-pptx 的 `para.runs` 看不到它 | 检查脚本按默认 18pt 估算，报页码框溢出 | 生成脚本给页码段落写 `defRPr` 字号 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v1/linsight/workbench/file_preview` | HTTP API | client 任务模式结果区、分享页 |
| 错误码 11025 `LinsightArtifactPreviewError` | 错误码，三语文案在 `packages/locales` 的 `api_errors` | client |
| `LinsightArtifactPreviewService.load_accessible_version` | 内部 Python API | `file_download`、`file_preview` |
| 技能包 `deck_template` 接口、插槽命名、`layouts.json` 结构 | 技能内部契约 | 模型生成的构建脚本、`deck_checks` |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| LibreOffice（含 Impress） | 系统依赖，`base.Dockerfile:12` | 裁剪过的环境（例如 114 只装了 writer）会转换失败，此时走 AC-23 兜底 |
| `packages/file-viewers` 把 pptx 映射到 pdf | 前端共享包（F089） | 该映射改变后，预览会失效 |
| 交付物键 `linsight/final_result/{svid}/{file_id}{ext}` | 隐式数据契约（`linsight/domain/utils.py:561`） | 键格式改变后，归属校验会拒绝合法文件 |
| 技能种子化按字节复制，且不按扩展名过滤 | `builtin_skill_seeder._read_bundle` | 若加了扩展名白名单，模板会被丢弃 |

### 6.3 发版契约登记

- 表 1 增加一行：无新增领域对象，F111。
- 表 3 增加 F111 的依赖：F089 和既有内置技能机制。
- 已分配模块编码增加 11025。
- 本功能不新增不变量，并遵守 V3-INV-7：派生预览不改变原文件下载的含义。

---

## 7. 测试与可观测

- **技能包单测**（`src/backend/test/linsight/test_pptx_templates.py`）：
  - 每份模板都能打开；`layouts.json` 里的每个插槽在 pptx 中都存在；示例文字一致。
  - 走一遍 `Deck` 全流程后，产物能重新打开、原型页已删除、manifest 正确。
  - 四项新检查做双向测试：坏样本能命中，按模板正确填写的好样本保持安静（AC-11）。
  - 种子化测试确认 `templates/**` 的字节随技能包下发（AC-13）。
- **预览服务单测**（`src/backend/test/linsight/test_artifact_preview_service.py`）：
  - 覆盖权限四种情形：所有者、管理员、分享、无权。
  - 覆盖归属校验、缓存命中、锁竞争返回 `converting`、转换失败返回 11025 且不写缓存。
  - mock MinIO、Redis 和转换函数，CI 不依赖 soffice。
- **前端**：`artifactUtils` 补单测；手动验证 ready、converting、失败三种状态，以及分享页。
- **端到端**（AC-30）：在 114 上用三类题目，分别在改造前后各跑一次，渲染逐页联系表归档到 `evidence/`。114 缺 Impress 组件，所以预览验证放在装有完整 LibreOffice 的环境（116 或 180）上做。
- **可观测**：转换耗时、失败原因记为 `logger.info` 和 `logger.warning`，带上 `svid` 和 `file_id`。
- **手动验证命令**：
  - 单测：`cd src/backend && uv run pytest test/linsight/test_pptx_templates.py test/linsight/test_artifact_preview_service.py test/linsight/test_builtin_skill_scripts.py test/linsight/test_builtin_skill_seeder.py`
  - 重新生成模板：`cd src/backend && python scripts/pptx_templates/build_templates.py`，然后用 `soffice --headless --convert-to pdf` 渲染逐页检查。
  - 端到端：在任务模式勾选代码执行器，输入"做一份介绍思源电气的 PPT，央国企风格"。完成后在结果区点开 pptx，确认依次出现生成中、逐页预览、提示条；再用分享链接打开同一结果，确认能预览。
  - 前端检查：`cd src/frontend && pnpm lint && pnpm typecheck && pnpm check-i18n`

---

## 8. 后续改进与不打算做的事

- **既有安全缺口（本期不修，单独提出）**：
  - `file_download` 不校验 `file_url` 是否属于该会话版本。只要能访问某个版本，就能签出任意对象键。
  - `download-md-to-pdf-or-docx` 和 `batch-download-files` 同样不校验。
  - 建议另立一个 hotfix：抽出 `load_accessible_version` 后，补上前缀校验。
- **第二期**：声明式格式加编译器、工具层门禁、模板选择界面、企业模板库、配图。
- 新检查升为 ERROR 的时机：AC-30 标定后决定。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-27 | 初版 | spec 确认 |
| 2026-10-27 | 预览转换：先占转换名额再加锁，加锁后复查缓存，锁按持有者令牌释放；转换失败写 5 分钟失败标记（AC-23 改为冷却期后重试）；文件读写、LibreOffice 和页数统计整体移出事件循环 | `/code-review` 指出锁过期后重复转换、误删他人锁、失败后每次轮询重转、阻塞事件循环 |
| 2026-10-27 | 技能脚本：基线扣除改为整条消息一致才扣；清单记录每页形状名，与文件对不上即忽略；表格列数与模板不同时不用模板列宽；超容量提示的页码按位置计算；`deck_checks` 改为在 `run_report` 内导入，加载失败仍输出基础体检；瀑布图减项标签带负号，累计值跌破 0 时报错 | `/code-review` 指出真实溢出被模板基线吞掉、旧清单误用、表格超宽、页码错、导入失败无输出、减项标签无符号 |
