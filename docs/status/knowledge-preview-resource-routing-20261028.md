# 知识空间资料预览与下载地址修复

日期：2026-10-28

## 根因与证据

13001 的知识空间 6 / file/4（FILE120.pdf）在已登录的 macOS Chrome 中复现 PDF 加载失败。预览接口返回 `/bisheng/original/4.pdf`，原实现将其转换成 `/workspace/bisheng/original/4.pdf`。线上该路径返回 HTTP 200、Content-Type `text/html`、4494 字节站点首页，浏览器继续进入 404 页面。使用相同签名访问后端返回的根路径，响应 HTTP 200、2024 字节、文件头 `%PDF-1.3`。PDF 主库和 worker 均为 3.10.111，worker 正常返回 JavaScript。

PPTX 的代码路径优先读取后端生成的 `preview_url` PDF，并复用同一个地址解析函数，受同一问题影响。后端尚未生成转换结果时，页面保留既有转换失败状态。用户补充 PPTX 来自同事测试，本轮按代码链路和转换结果夹具验证。

## 实现

- 对象存储资源使用站点根路径 `/bisheng/`、`/tmp-dir/`；历史页面前缀与重复前缀统一还原为对象根路径。
- 签名查询参数按原字节保留；绝对对象存储地址继续通过站点代理访问，外部文档地址、根相对资源、blob/data 地址保留各自语义。
- 知识空间列表下载和独立预览页下载共用地址处理；下载继续先调用已有受权限控制的下载接口。
- PDF、PPTX 生成的 PDF、富文档、媒体与转写内容通过现有共享解析入口获得修复。

## 基线与验证

- 初始远端基线 `53737ea4fc0cb8b2d27f043c428d08d209209483`；验证期间快进同步 `0e84344aeb02f980c003584b32013960b29dc429`。新增目标内容仅涉及后端审计及其文档，前端验证代码保持一致。
- 分支 `codex/knowledge-preview-resource-routing`，工作目录 `.worktrees/bisheng-knowledge-preview-resource-routing`。
- 新增 28 项测试通过，覆盖 10 种资源路径、历史前缀、签名保留、外部资源、路由页格式选择、PPTX 转换失败与原文件下载。将原地址解析实现放回同组测试，复现 19 项失败。
- 6 组 / 69 项定向回归通过，涵盖引用定位、引用失败、附件收集和 Linsight 引用转换。
- 前端 workspace 的 ESLint 与类型检查全部通过，涵盖 Client、Platform 和共享文件预览包；Client 包含 1484 个严格类型文件。Client 生产构建、逐文件架构守卫与差异检查通过。
- `TopBar.test.tsx` 在当前与未修改的参考分支均因 `filenamify` ESM 加载失败而在用例执行前终止；此项为测试环境限制。
- macOS Chrome 本地组件验证使用修复后的解析函数、真实 PDF.js 与现有 PdfViewer，实际 file/4 渲染为 2 页；PPTX 转换结果夹具亦渲染为 2 页。夹具代理只服务本地已取得的 PDF，未执行真实 PPTX 转换。

## 发布与验收

本次交付为前端源码修复，目标分支为 `dataelement/bisheng:feat/bisheng-work-120-main`；合并状态以 PR 记录为准。13001 尚待部署配套 Client；Windows Chrome、同事原始 PPTX 的转换与预览、其他格式真实文件仍待测试环境验收。无需桌面或 Harness 代码变更。

复测：打开 PDF 和已完成转换的 PPTX，确认正文与页数正常；执行下载确认取得原始格式；抽查 Word、Excel、图片和文本；检查文件请求返回实际内容。保留一份转换失败的 PPTX，确认页面呈现转换失败状态。

本机证据：主工作区 `outputs/knowledge-preview-20261028/`，含构建与静态检查日志、原实现失败日志、PDF/PPTX 夹具截图及本地验证入口。访问凭据与带签名地址保持在报告之外。
