# 文件预览与引用共享实施计划

> For agentic workers: Use superpowers:executing-plans to implement task-by-task. The confirmed spec and design are binding; no implementation checkpoint between tasks.

**Goal:** 两端共用预览和引用内核，图表脚本单份维护、独立输出。
**Architecture:** 扩展 file-viewers 和 chat 的纯入口/视图，宿主适配权限、地址及后台编辑；diagram-runtime 提供原样脚本与去重加载。
**Tech Stack:** 既有 React18 / TypeScript / PDF.js3.10.111 / mammoth / Vite6 / Vitest、Jest；不新增外部库。
**Spec:** [spec.md](spec.md) · [design.md](design.md)。

## Global Constraints

- client 为显示基准；不改后端、权限合同、图表版本，不新增格式/状态库/视觉规范。
- HTML 无 allow-same-origin；PDF 页码边界显式转换；后台虚拟滚动和切片编辑保留。
- 共享入口避免 eager 重依赖；单文件≤600行；三语言、命名导出和严格TS；不增加 suppressions。
- 现有主目录另有任务改 SSE 文件，禁止混入。测试单 worker、构建串行；不用全局 stash/reset/restore/clean，不重新安装主目录依赖。
- 仅在隔离开发分支提交；不自动合并/推送3.0或release。

## Review Focus

- A→B→A、卸载和旧PDF渲染完成不能改当前内容（T2/T4/T6）。
- 临时上传、签名失效、跨租户/分享拒绝不得串缓存或绕权（T5/T6）。
- PDF 0起/1起页码、非等高页、缩放及后台框选不能漂移（T4）。
- 图表多请求、超时后旧onload、失败重试及独立base输出（T1）。
- PDF渲染失败与下载失败不同；HTML storage shim、原文件下载及懒加载（T2/T3/T4/T7）。

## 状态

| 文档 | 状态 |
| --- | --- |
| spec.md | 已确认 |
| design.md | 已确认（用户“确认”简版HTML） |
| tasks.md | 已自查AC全覆盖；实施中 |

### Task 1: 图表资源与加载器

Files: 新建 `src/frontend/packages/diagram-runtime/{package.json,tsconfig.json,src/index.ts,src/loader.ts,src/loader.test.ts,assets/manifest.json,assets/*.min.js}`；新建 `config/diagramAssets.ts` 和 `config/diagramAssets.test.ts`；修改两端 vite.config/package.json、pnpm-lock.yaml、两端 Mermaid loadScript 和后台 BaseChart；删除两端public根脚本副本。
Interfaces: `loadDiagramLibrary(kind:'echarts'|'mermaid', options:{baseUrl:string;timeoutMs?:number}):Promise<unknown>`；`diagramAssetTargets():Array<{src:string;dest:string}>` 由config提供；资源dest根目录。
覆盖 AC: AC-15、AC-16、AC-17、AC-18、AC-20。
- [x] 写 loader 测试：同URL并发共享Promise/仅一script、已就绪全局直接返回、base路径正确、onerror/超时清理并可重试、旧回调不结算新尝试。写资源测试：公共manifest两脚本hash、targets绝对路径、两端不依赖对方build。
- [x] 单worker运行并观察RED；实现最小loader/manifest/targets，原字节移动脚本，接入所有真实加载入口。
- [x] 跑 `pnpm --dir src/frontend/packages/diagram-runtime test` 和 `pnpm --dir src/frontend test:config`，期望相关全PASS；单独dev/build资源HTTP和hash验证留T7一起执行。
- [x] 仅暂存本任务文件并提交 `refactor(frontend): share diagram assets and script loading`。

### Task 2: 预览资源生命周期及安全HTML

Files: 新建 `packages/file-viewers/src/{types.ts,usePreviewResource.ts,usePreviewResource.test.tsx,html/sandboxedHtml.ts,html/sandboxedHtml.test.ts}`；调整原types（保留既有Excel类型）、public exports；client sandboxedHtml转接。
Interfaces: `PreviewResource {originalUrl:string;previewUrl:string;fileName?:string;fileType?:string}`；`PreviewPdfBBox {page:number;bbox:[number,number,number,number]}`；`usePreviewResource<T>(key:string, load:(signal:AbortSignal)=>Promise<T>):{status:'loading'|'ready'|'error';data?:T;error?:unknown}`；`buildSandboxedSrcDoc(html:string):string`/sandbox属性保持已有语义。
覆盖 AC: AC-04、AC-08、AC-12、AC-13、AC-19。
- [x] 写真实hook异步顺序测试：A→B→A、卸载、取消、失败重开；HTML测试doctype保留、shim先于用户脚本、无同源授权。
- [x] RED后提取client安全helper和可取消加载；校验返回受当前key/代次控制，不把异常转成原始提示。
- [x] 运行file-viewers单worker测试、strict types；原client sandboxedHtml现有测试回归，期望PASS。
- [x] 提交 `refactor(preview): share resource lifecycle and HTML sandbox`。

### Task 3: 非PDF视图与两端文件预览接入

Files: 新建 `packages/file-viewers/src/viewers/{DocxViewer,MarkdownViewer,TextViewer,HtmlViewer,ImageViewer,MediaViewer}.tsx`、格式选择/locale/组件tests和lazy子入口；两端知识库对应组件与引用预览宿主改公共消费；依赖从现有包移到所属包（不升级）。
Interfaces: 各视图 `PreviewViewerProps {resource:PreviewResource;zoomLevel?:number;locale:PreviewLocale;onError?:(error:unknown)=>void}`；`PreviewLocale`含loading/failed/empty/各预览名称等宿主三语言值。`MediaViewer`额外transcript资源；已有Excel接口不变。
覆盖 AC: AC-01、AC-02、AC-03、AC-04、AC-05、AC-07、AC-08、AC-19、AC-20。
- [x] 写组件测试：DOCX清洗保留表格图片、Markdown代码无多余换行、TXT按文本显示、HTML沙箱、图片错误、媒体original播放/preview转写；测试切换与加载失败不串状态。
- [x] RED后基于client实现提取，以薄适配保留宿主缩放/布局和已存在动作；迁移依赖版本按lockfile解析值记录。
- [x] 两端相关预览/Excel现有测试 + 新组件测试 + 共享包types/lint，期望PASS。
- [x] 提交 `refactor(preview): share document image and media viewers`。

### Task 4: PDF公共绘制与编辑适配

Files: 新建 `packages/file-viewers/src/pdf/{usePdfDocument,PdfPage,PdfViewer,coordinates,types}`及测试、lazy入口；修改platform `components/bs-comp/FileView.tsx`、client `knowledge/FilePreview/index.tsx`/`viewers/PdfViewer.tsx`。
Interfaces: `usePdfDocument(url:string,assets:{workerUrl:string;cMapUrl:string})`返回loading/error/document并销毁loadingTask；`PdfPage`消费document/pageIndex/width/zoom/drawText，提供 `renderOverlay(metrics)`、`onMetrics(metrics)`、`onError(error)`；`metrics {pageIndex,originalWidth,originalHeight,width,height,scale}`。共享只读PdfViewer沿用client现有props，仅bbox类型改公共定义；后台onSelectLabel/onPageChange既有payload不变。
覆盖 AC: AC-01、AC-06、AC-08、AC-11、AC-13、AC-14、AC-19、AC-20。
- [ ] 写坐标/页码测试、真实渲染任务替身测试：0/1起边界、多尺寸、缩放高亮/框选映射、多实例隔离、取消不报错、当前文档多页失败仅一次、旧文档失败忽略。
- [ ] RED后提取共享PdfPage及session；后台保留react-window/框选薄适配，移除模块全局页缓存和固定DOM id；client迁公共只读视口。
- [ ] 跑原PdfViewer.errors测试及新PDF/编辑适配回归，types/lint；浏览器真实Canvas/定位/框选在T7验证。
- [ ] 提交 `refactor(preview): share PDF rendering with host editing overlays`。

### Task 5: Citation纯工具与宿主资源合同

Files: 共享 `packages/chat/src/citations/{index,types,markers,normalize,referenceItems,export,documentResources}`及fixtures/tests；整合现有content/citationMarkers/citationPreview/types；两端citationUtils逐个迁移/转接。
Interfaces: 复用ChatCitation/CitationDisplayData/PreviewState；`CitationServices {scopeKey:string;getCitationDetail;resolveCitationDetails;getCitationUnresolvedReason;resolveDocumentUrls;download;openArticle;localize}`（已有服务签名沿用design）；resolver `Promise<PreviewResource>`，宿主明确拒绝继续reject，不走legacy权限回退。PDF bbox type-only引用file-viewers。
覆盖 AC: AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-20。
- [ ] 收集两端真实旧引用/导出/临时/知识/媒体输入fixture并写差异对照测试，标记、片段编号、多个itemIds、顺序/分组、剥离/烘焙结果保持。
- [ ] RED后收敛纯工具；权限/URL调用留宿主，以同scope in-flight复用、不跨token/租户缓存；临时引用不调knowledge/file_share。
- [ ] 跑共享chat及两端citation/bake/导出已有测试，纯子入口无DOM导入及无重依赖测试，期望PASS。
- [ ] 提交 `refactor(citation): unify parsing and document resource contracts`。

### Task 6: Citation来源列表与文档预览

Files: 新建 `packages/chat/src/citations/{CitationReferences,CitationDocumentPreview,CitationSourceIcon,useCitationPreview,useCitedPassageLocate}`及组件测试/子入口；两端ReferencesDrawer/DocumentPreviewDrawer/Markdown服务薄适配。
Interfaces: `CitationDocumentPreview({preview,services,compactMode})`；`CitationReferences({content,webContent,citations,services,onPreview})`；shared预览使用T2/T3/T4输入及T5服务，不读宿主store。两端移动导航/抽屉容器/后台只读能力留宿主。
覆盖 AC: AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-19、AC-20。
- [ ] 写组件和真实adapter测试：引用来源/文件正确、原文件下载、PDF多片段/非PDF文本定位、权限拒绝不请求文件、A→B→A不串、切换账号/分享scope不复用、只读无写入。
- [ ] RED后迁client来源视图，保留后台历史协议和媒体特性，接入共享Markdown、旧日常/任务已有消费入口，移除业务无关旧副本。
- [ ] 跑chat及两端引用/共享会话/只读/标注相关测试，期望PASS。
- [ ] 提交 `refactor(citation): share reference lists and document previews`。

### Task 7: 全部入口清理及联合验收

Files: 两端实际调用/无调用副本、包边界扫描tests、F089 e2e-checklist/verification/tasks/design/release-contract。
Interfaces: 不新增运行时合同；检查T1–T6输出一致。
覆盖 AC: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20。
- [ ] 扫描静态/动态/barrel调用，删除失去入口的副本，第三方vditor按可达性保留理由；写包边界回归避免宿主反向import。
- [ ] 跑相关全测试、lint/typecheck、i18n/archguard、串行两端构建；记录既有基线，禁止扩大suppressions。
- [ ] 用 /e2e-test 生成并执行适用的前端验证：真实文件、Canvas/框选/定位/沙箱、独立dev与生产资源、PWA清单、懒加载、三语言/窄屏；模拟与真实环境区分。
- [ ] fresh reviewer全分支审查，修复重要问题；/sdd-code-review 对照AC；提交验证文档，保留开发分支待用户验收，不自动推送/合并。

## 实际偏差记录

- 开发分支基于fetch后的 `origin/feat/3.0.0`，最新合并为4767247ca；原主目录未提交SSE清理及测试文档保持不动。
