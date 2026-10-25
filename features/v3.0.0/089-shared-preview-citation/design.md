# 文件预览与引用溯源共享设计

关联：[spec.md](spec.md) · [discovery.md](discovery.md)。版本 v3.0.0；更新于 2026-10-23。

状态：规格及设计已确认，实施中。Task 1–3 图表资源、文件生命周期、安全 HTML 和非 PDF 格式视图已落地；PDF 与引用仍在实施。基线 `feat/3.0.0` / `38395b198`。

## 1. 目标与非目标

沿用 client 展示，把文件预览和引用来源链路的公共逻辑收进共享包，让两端消费同一实现。后台编辑、宿主权限、签名地址获取与移动导航仍由业务适配负责。ECharts/Mermaid 保持现有版本、字节和访问路径，以单份静态来源服务两个独立前端。

不新增格式、解析引擎、UI/状态管理库、CDN 或资源服务器；不修改后端、数据库、会话执行和 QA 写入合同，不重设计组件样式。

## 2. 关键约束

遵循 [constitution](../../../docs/constitution.md) C1–C8 及 [release-contract](../release-contract.md)。公共 UI 仍遵守 `@bisheng/ui` 纯展示合同，文件/引用业务组件不放入 UI 基础库。

- 前后台可独立启动和部署；platform base 当前为空，client 为 `/workspace`；后台还支持自定义前缀。worker、cmaps、图表脚本地址均以宿主 base 生成。
- PDF 两端均用 pdfjs-dist 3.10.111，后台另有 react-window 虚拟滚动、文字/批注及框选编辑。PDF 页面尺寸、坐标和滚动不是简单替换 UI。
- client 预览器及 pdfjs/mammoth 当前延迟加载；公共包的聚合导出不能把这些大依赖带入聊天首屏。
- 显示以当前 client 为基准，不改设计规范。共享按钮、选项和弹层使用已落地组件；普通抽屉组合遵循现有 client，不另造视觉模式。
- 现有预览正文用于入库时须保持一致；抽离不能自动重解析、覆盖切片或发起写入。

## 3. 方案及决策

### 3.1 扩展已有文件预览包

**选定**：扩展 `@bisheng/file-viewers`，沿用 Excel，按格式拆出视图、内容加载和 PDF 内核。两端薄入口负责布局、工具栏、宿主 URL/权限适配。

**否决**：后台直接 import client 文件，会引入 `~/`、Recoil、路由和 client API；全部塞进 `@bisheng/ui` 则违反基础库合同。

**原因**：现有包已被后台 PreviewFile、Citation 抽屉和 client XlsxViewer 使用，适合承载不依赖宿主业务的预览。现有 Excel 依赖及语言加载不重做。新组件所有新增文案经 props/locale 传入，避免扩大公共包对宿主 i18n 的耦合。

**重新考虑条件**：将来需要脱离 React 使用预览内核，才单独拆出渲染无关模块。

### 3.2 PDF 共享渲染内核，保留后台编辑布局

**选定**：共享文档会话、单页绘制/文字/批注层、尺寸及坐标转换、渲染取消。client 默认只读视口迁入共享包；后台虚拟列表和框选业务留在薄适配中，调用同一单页渲染器并通过 overlay 接口挂载选择区。

**否决**：用 client 当前只读 PdfViewer 直接覆盖后台 FileView，会丢失编辑层、原滚动回调及长文档虚拟化；保留两份完整 renderer 则去重不彻底。

**原因**：后台 FileView 的 `onSelectLabel`、`onPageChange`、`scrollTo` 和页宽回调被切片编辑消费，且文件内有模块级 page cache/scale。搬运时将这些缓存改成文档实例所有，防止多个预览互相污染。两端绘制复用，布局策略可不同。

**重新考虑条件**：后台编辑业务退休或明确统一滚动体验时，再合并两种视口控制。

### 3.3 引用内核和来源内容归共享会话包

**选定**：在 `@bisheng/chat/citations` 子入口统一纯类型/解析，在对应视图子入口提供来源列表和预览内容；沿用该包已存在的 citationMarkers、citationPreview、MarkdownServices。共享视图调用文件预览包，不反向依赖宿主。

**否决**：新建第三套独立引用算法，或把两端整个 citationUtils 直接拼接后保留重复导出。

**原因**：共享 Markdown 已有引用类型及解析，继续统一可以消除目前“共享标记 + 两端列表/预览 + 两端工具”的多重来源。按函数建立行为对照，以 client 为基准保留后台历史格式兼容，不按行数选择胜方。纯子入口不触发 mammoth/pdfjs、宿主 API 或浏览器初始化。

**重新考虑条件**：出现真实的非会话引用产品入口时，才将纯引用域整体从 chat 包移出；避免目前过早新增包层次。

### 3.4 权限和地址获取作为宿主服务

**选定**：共享引用视图接收详情解析、可访问状态、文件 URL 解析、下载和文章导航服务；不自己拼 API 或读登录态。client 保留现有文件分享 API/分享上下文，platform 保留现有后台服务。共享包只处理成功的数据及显式失败状态。

**否决**：把 client 登录后的知识库取地址接口无条件用于访客/临时上传；或失败后通过另一接口获取原本受限内容。

**原因**：临时引用不是知识文件；知识文件的原文件和派生预览文件也不同。当前代码中 client 的临时引用明确禁止调用 knowledge/file_share。该分类和权限来源要留在宿主合同中。

**重新考虑条件**：后端提供覆盖全部引用类型与访问上下文的统一接口时，再简化宿主适配。

### 3.5 图表脚本原样复制

**选定**：新增业务无关的 workspace 包 `@bisheng/diagram-runtime`，持有现有两份一致脚本的一份源文件、白名单 manifest 和公共脚本加载器。两端使用现有 vite-plugin-static-copy，从公共文件复制到各自 build 根目录；开发模式由该插件直接提供文件，不先生成 app/public 副本。

路径保持 `<base>/echarts.min.js`、`<base>/mermaid.min.js`。复制目标在共享 config helper 中定义，路径基于配置文件位置，不依赖启动 cwd。不对这两个资源做 Rollup import、转译或再次压缩；现有生产 gzip/br 是传输压缩，可照常保留。CI 比较原 JS 的 SHA-256。

**否决**：保留两端 public 源文件并手动同步；借用另一前端 public/build 的路径；新增 CDN；将压缩脚本当普通 ESM 编译。

**原因**：两端当前文件分别字节一致，直接复制即可；原脚本依赖 window 全局，保持原 bytes/加载模式能避免打包环依赖。现有 static-copy 已为两端提供 PDF worker/cmaps，无需新插件。

**重新考虑条件**：未来产品明确需要中央资源服务，或库正式改成受控 ESM 依赖时，再评估输出路径和加载方式。

## 4. 当前代码与拟实施数据流

### 4.1 当前实际调用

- platform `KnowledgePage/components/PreviewFile.tsx` → 本地 DocxFileViewer / TxtFileViewer / `bs-comp/FileView.tsx`；Excel 已共享。
- client `knowledge/FilePreview/index.tsx` → viewers 下各格式组件，lazy import pdfjs、DOCX、Excel；文件预览还被 Citation 抽屉和其他入口复用。
- platform `PlatformChatMarkdown`、client `ClientChatMarkdown` → 共享 ChatMarkdown → 各宿主 CitationDocumentPreviewDrawer；来源列表、工具函数仍分别实现。
- client citationUtils 还被导出/复制、Linsight 制品等调用；platform 工具还被 FlowChat/messageStore 等调用，需追踪入口，不以文件存在推断全部活跃。
- 后台看板 BaseChart 使用根目录 ECharts；两端 Mermaid 模块给共享会话提供 loadScript。platform public/vditor 中另有内嵌脚本，属于第三方分发包，不能同根资源一起直接删。

### 4.2 实施后的流程

文件入口 → 宿主确认能力/解析可访问地址 → 共享加载与对应视图 → 事件回传业务入口。失败/切换通过实例代次隔离，完成后释放资源。

引用标记 → 共享解析/来源分组 → 宿主按当前上下文取引用详情和资源地址 → 共享来源列表/预览 → 宿主下载/导航。只读上下文不挂载写入业务。

图表视图/看板 → 公共 loader（固定 kind、宿主 base）→ 自己站点的压缩 JS → window 全局对象；多个请求复用同一次 in-flight 加载。

### 4.3 模块职责及拟定接口

| 模块 | 做什么 | 不做什么 |
| --- | --- | --- |
| file-viewers/types | 通用预览元数据、PDF bbox/页面指标、locale 与能力接口 | 不引用 chat 或两端 alias |
| file-viewers/viewers | DOCX、文本、Markdown、HTML、图片、媒体及默认 PDF 视口 | 不读宿主 store/路由，不鉴权、不写业务数据 |
| file-viewers/pdf | 文档生命周期、单页/文字/批注绘制、坐标/尺寸、取消 | 不保存切片，不持有跨文件全局 page cache |
| chat/citations | 引用数据标准化、分组、文字定位和来源/原文视图 | 不直接 import Axios、宿主 API、Recoil 或路由 |
| 两端 preview/citation adapters | 地址/权限/下载/文章导航、移动端布局、后台编辑 overlay | 不复制公共解析或文档 renderer |
| diagram-runtime | 脚本资源和按 URL 去重的加载器 | 不编译供应商脚本，不持有会话状态 |
| config/diagramAssets | 两端开发与构建的统一静态复制配置 | 不从任一 app 的 public/build 取源文件 |

所有新增文件 ≤600 行、严格 TypeScript、组件命名导出。失去调用方的旧实现删除；若必须保留旧路径，只允许无逻辑转接或类型导出，不保留第二份实现。新增调用直接用公共入口。

## 5. 关键合同及已知坑

### 5.1 预览输入与 PDF 合同

- 公共资源元数据区分 `originalUrl`、`previewUrl`、原格式及实际预览格式。转成 PDF 的 PPT 仍是 PDF 渲染，不算新增 PPT 原生支持。
- 宿主负责 URL 授权和原有 host/base 适配；公共组件只能读取已授权 URL 或宿主提供的加载器。跨域签名 URL 不盲目替换 host，不从失败地址推导另一权限路径。
- PDF 使用文档级 `sessionId`，页面绘制提供 `pageIndex`（统一 0 起）、原始宽高、显示宽高、scale、容器 ref 和 overlay 插槽。PDF.js getPage 是 1 起，仅在公共内核转换；旧后台及历史引用输入在宿主适配边界标准化，禁止凭数值大小猜测页码。
- PDF bbox 类型定义归 `file-viewers/types`；chat 仅 type-only 引用或导出，file-viewers 不反向依赖 chat，防止公共包环依赖。
- bbox 保留 `page` + `[x1,y1,x2,y2]` 既有语义，按 document viewport 显式换算。后台旧 `onPageChange(offset,height,paperSize,scale)` 在适配层据共享指标恢复原合同，`onSelectLabel` 仍传原 label id/active，不转换成新写入格式。
- 转写文本的底部留白由宿主传入：client 保留 114px 为 AI dock 留位，后台使用 16px；不把客户端页面布局强加给后台。
- 默认只读视口提供 zoom、targetPage、targetBBox、highlightBboxes 及 currentPage 回调；编辑能力只通过后台 overlay 暴露。文字/FreeText 批注层是公共渲染能力，编辑操作仍由后台管理。
- PDF document loading task、page render task、observer、定时器及对象 URL 由创建者销毁；切换/卸载先失效再清理，旧回调不可更新新实例。每个文档会话渲染错误只提示一次，正常取消不提示；重开文件产生新会话。
- workerSrc/cmaps 由宿主资源 base 显式传入，继续固定现有 pdfjs 版本；公共模块 import 时不设置全局 workerSrc。

### 5.2 引用与宿主服务合同

- canonical 类型沿用共享包 `ChatCitation {citationId,type,itemId?,sourcePayload?}`，`CitationDocumentPreviewState {detail,itemId?,itemIds?,locateChunk?}`。保留历史字段与 alias 的兼容标准化函数；未知字段不注入 HTML。
- `CitationReferenceItem` 包含稳定 key、展示数据、可选多个 itemIds、detail/legacyPreview。显示分组去重不可丢失原引用顺序或片段，复制/导出剥离标记及烘焙引用的规则也迁为同源纯函数。
- `CitationServices` 提供 detail/批量resolve、unresolved reason、resolveDocumentUrls、download、openArticle、localize，以及授权上下文 `scopeKey`。共享层不假定所有适配器都能远程解析；拒绝状态先终止，不能自动走临时/legacy路径重取。
- URL resolver 返回 original/preview 及实际可预览格式，下载优先 original；媒体播放用 original、转写用 preview。临时引用沿用消息附带地址，不调用知识文件 API。
- in-flight 去重最多在同一个宿主授权上下文内按稳定身份复用；不跨账号/租户/分享 token 缓存，不长期缓存已签名 URL。关闭后重新打开允许刷新签名；显式拒绝不回退旧链接。
- 来源切换和预览切换都带代次/取消信号，A→B→A 也不接纳第一次 A 的过期结果。薄移动容器负责导航可见性；共享内容不读 Recoil。

### 5.3 HTML、DOCX、Markdown 与安全

- HTML 复用 client `sandboxedHtml` 的隔离策略与内存 storage shim；提取 helper 后原制品入口可转接共用，保持 doctype 在最前、iframe 能获焦，不开放 allow-same-origin。
- DOCX 沿用 mammoth，渲染前复用现有 sanitizeHtml 策略，兼容后台既有输出内容；Markdown 沿用 client 文件预览的受控插件链，不套用会话特殊协议。新增依赖仅移动既有依赖到所属 workspace 包，不升级版本；mammoth 两端已有不同声明，已核对 client 实际解析为 1.12.0，公共包固定此版本，没有升级或另拉新版本。
- shared Markdown 禁止恢复全局“每个换行加两个换行”的预处理；代码块/图表原文及复制内容保持原样。高亮库/语言注册保持既有分包边界，生产验证 TDZ 回归。

### 5.4 图表加载与复制合同

- `loadDiagramLibrary(kind, {baseUrl,timeoutMs})` 仅接受 echarts/mermaid，输出 Promise<对应库>；按完整资源 URL 记录 in-flight，已有匹配全局对象时直接返回。
- 同页换 base 不并行加载另一个版本；两种资源固定同一 manifest 版本。loader 只加载库，Mermaid initialize 等视图配置由现有渲染入口管理，不因改资源来源而全局重配。
- script onerror 或超时（默认 15 秒，可注入短值测试）会移除失败元素、清理 in-flight/timer 并 reject；成功也清理轮询。移除旧 script 不能保证浏览器撤销执行，延迟回调按尝试代次隔离；重试先检查同版本已就绪全局。
- 保留现有脚本的加载属性/全局导出方式，供应商版权头完整保留。manifest 记录来源、可从文件核实的版本、SHA-256；版本无法从文件确认时不编造。
- 当前两份生产 Dockerfile 都以整个 frontend workspace 为构建上下文并 COPY 到 /app；新增包位于同一上下文。验证单独构建 app 命令，不采用 platform-only 源码上下文；旧 dev.Dockerfile 的 npm/Node19 配置不在本次顺手修复。
- static-copy targets 只包含两个白名单文件及必要许可文本，dest 为输出根；不存在公共源应使构建失败。删除两端根 public 副本，构建 hash 测试防止重新分叉。
- client PWA 和压缩插件按原配置运行；实测生成的资源及 service worker 清单。public/vditor 内嵌依赖先追踪真实调用：活跃分发包不改其私有依赖版本；若引用/产物完全不可达，删除只在有调用证据且不破坏完整分发合同后执行。

### 5.5 实施落点索引

以下是拟新增/迁移落点，不表示代码已存在：

| 风险 | 处理位置 |
| --- | --- |
| PDF 页码/坐标、渲染取消、实例缓存 | `packages/file-viewers/src/pdf/{PdfDocumentSession,PdfPage,coordinates}`；platform `components/bs-comp/FileView.tsx` 只保留编辑/虚拟布局适配 |
| 原文件/预览地址、临时引用和授权作用域 | `packages/chat/src/citations/{types,documentResources}`；两端 `preview/citation` 服务适配器保留原业务入口 |
| 过期引用和文件回调 | `packages/chat/src/citations/useCitationPreview`、`file-viewers` 文档会话 |
| HTML 存储 shim/隔离及文档清洗 | `packages/file-viewers/src/html/sandboxedHtml` 与 `viewers/DocxViewer`；原宿主 helper 仅转接 |
| 脚本去重/超时、开发和构建资源路径 | `packages/diagram-runtime/src/loader`、`config/diagramAssets.ts`；两端 vite.config 的 static-copy 配置 |

文件名可在任务拆解时调整；职责与合同不变。

## 6. 对外依赖与影响入口

### 提供的接口

| 接口/产物 | 消费方 | 兼容要求 |
| --- | --- | --- |
| file-viewers 分格式 lazy 子入口、类型及 PDF 内核 | 两端知识库、引用、既有文件预览消费者 | 不 eagerly import 全部重依赖；保留原宿主工具栏和业务事件 |
| chat/citations 纯类型/解析与视图子入口 | 两端 Markdown/引用列表、复制导出、任务制品已有调用 | 不新增会话状态，不改变引用协议；纯子入口可在无 DOM 环境导入 |
| diagram-runtime loader + 两个静态 JS | 会话 Mermaid/ECharts、后台看板及实际其他调用 | 当前路径、window 全局、库版本和业务功能保持 |

不新增 HTTP/Python 接口或后端持久化结构。

### 依赖及风险

| 依赖 | 风险及适配责任 |
| --- | --- |
| 后端引用 payload、bbox、文件地址及已有授权接口 | 字段多态/签名过期，宿主规范化且按原权限服务取数据 |
| PDF.js 3.10.111、worker/cmaps | 主库/worker 必须匹配，CJK 字体缺 cmaps 会空白；禁止隐式 CDN |
| mammoth、DOMPurify、Markdown 插件、Excel 现有依赖 | 移动依赖需锁定当前解析结果，生产延迟分包不回退 |
| viteStaticCopy、PWA、compression、各自容器构建上下文 | 公共源需存在于两端构建上下文，开发路径及 SW 生成时序需验证 |
| F086 会话、F088 错误合同 | 预览/解析不触发发送或写操作，取消/全局拒绝不可重复弹普通错误 |

## 7. 验证与可观测

分层验证：纯解析与历史 fixture 差异对照；真实组件控制加载、取消、切换和编辑 overlay；两端真实 adapter 检查地址/权限，避免 mock 掉待验证逻辑；浏览器验证 PDF 画布/定位、HTML 沙箱、拖动框选、图表脚本加载及 UI 回归。

使用测试账号和可丢弃文件，先记录各格式基线。覆盖知识库、工作流/助手调试、引用列表、标注/日志只读和 client 日常/任务已有预览入口。模型生成质量不在本次验收范围。具体账号/环境由现有测试配置选择，不在文档写凭据，也不自动部署共享环境。

本地验收入口（启动命令从 `src/frontend` 执行 `pnpm dev:platform` / `pnpm dev:client`；端口固定，已有服务先查明归属，不自动停其他任务）：

- 后台知识文件：`http://localhost:3001/filelib/<knowledgeId>`，选取测试文件查看/编辑切片；工作流 `/flow/<id>`、助手 `/assistant/<id>` 中打开调试及引用。
- 前台知识文件：`http://localhost:4001/workspace/knowledge/space/<spaceId>`；日常 `/workspace/c/<conversationId>`、任务 `/workspace/linsight/<conversationId>` 及工作流/助手 `/workspace/app/<fid>/<type>` 检查现有引用入口。
- 后台 `/label`、`/log` 从真实列表进入会话；不要手拼业务 ID；用已有可授权账号及普通用户验证可访问/不可访问和只读行为。
- 资源 HTTP 检查：分别请求 `http://localhost:3001/echarts.min.js`、`http://localhost:3001/mermaid.min.js` 及 `http://localhost:4001/workspace/echarts.min.js`、`http://localhost:4001/workspace/mermaid.min.js`，确认返回脚本而非 SPA HTML；生产 preview 同样验证。

实施后在 `src/frontend` 执行包/改动文件 lint 与类型检查、相关单 worker 测试、i18n 检查，再串行 `pnpm build:platform` / `pnpm build:client`。独立启动两端 Vite 和生产 preview，分别请求根路径及 `/workspace` 的图表脚本、worker/cmaps；比对源文件与两端输出 JS 的 SHA-256，验证仅启动一个 app 时也可渲染。按真实打包入口检查 PDF/DOCX 仍为延迟模块、无 HighlightJS 初始化异常，校验 PWA 缓存清单资源存在。

错误证据保留原 cause/context，不自动记录签名 URL/文件内容；用户提示走现有本地化与去重出口。验收报告区分自动测试、模拟浏览器和真实业务结果，既有质量基线单独记录，不通过扩大 suppressions 消除失败。

## 8. 交付波次及保留边界

建议顺序：① 静态图表资源/loader；② 非 PDF 文件视图及媒体；③ PDF 共享内核与后台编辑；④ Citation 纯工具、来源列表及预览接入；⑤ 清理副本与两端联合回归。每波保持两端可构建，未迁移入口明确列出，最终 AC-20 按真实调用清零公共逻辑副本。

继续保留业务配置、权限/URL 服务、客户端移动导航、后台 PDF 编辑控制和虚拟布局。这些不能为了删除文件而伪装成公共层。新格式和第三方分发包升级另行立项。

| 日期 | 修订 |
| --- | --- |
| 2026-10-23 | 初版设计待确认；规格确认后细化预览、引用与图表资源合同 |

PDF 编辑适配补充：后台继续使用虚拟列表，页尺寸缓存限定在当前预览实例；滚动通知保留原四个参数，增加可选的逐页位置上下文，供原有选区定位提示适配混合尺寸及 0 起始页码。只读入口不绑定选择写入。
