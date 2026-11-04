# 应用历史附件下载路由修复

## 基线与范围

- 目标分支：`dataelement/bisheng:feat/bisheng-work-120-main`。
- 实现前与提交前在线核对的基线：`3120e714fa4ed492884cade11a128341d03eb105`。
- 修复分支：`codex/app-attachment-download`；独立目录：`bisheng-app-attachment-download-20261102`。
- Client `3.0.0-beta5`，pnpm `9.15.9`，按现有锁文件安装，依赖声明与锁文件保持原内容。

## 根因与修正

应用消息的 `AppChatFileList` 经 `AppChatFileChip` 将历史文件 URL 交给 `ChatFile`。原下载处理把绝对 URL 的主机名替换为 Client 的 `BASE_URL`，例如存储地址 `/bisheng/chat/...pdf` 被改成 `/workspace/bisheng/chat/...pdf`。请求进入 SPA 路由，前端 catch-all 返回 HTTP 200 的 HTML；下载工具按原文件名保存响应，用户得到带 `.pdf` 扩展名的 HTML。

`ChatFile` 现在复用现有 `resolveKnowledgePreviewUrl`，让已知对象存储路径经 origin 级 bucket 代理访问，兼容历史 Client 前缀及根相对路径，保留原签名查询、编码后的对象名和下载文件名。第三方资源、API URL 与 blob URL 沿用其自身地址。空地址继续保持原处理。

组件补齐 Props 类型并纳入 strict 检查，调用方改为具名导入。空扩展名沿用 `FileIcon` 的文本图标默认值；现有卡片样式保持原内容。通过 ESLint 官方 prune 命令移除了该文件已失效的正则转义 suppression。

## 验证证据

- 新增组件回归使用真实 `AppChatFileList`、`AppChatFileChip`、`ChatFile` 和 URL 解析函数。下载传输接本地 HTTP 夹具：正确对象路径返回合成 PDF 响应，其余路径返回前端 HTML；断言点击后的请求地址、响应类型与字节。首轮旧实现 16 项中 13 项失败，其中点击合法存储地址得到 `text/html`。
- 最终新增 17 项覆盖历史字段别名、历史前缀、根相对及协议相对路径、临时桶、签名参数、编码对象名、中文文件名、第三方/API/blob URL、空路径和 HTTP 路由。
- 应用聊天、历史附件与预览 URL 组合：11 组 / 88 项通过。
- workspace 全量 `lint` 通过，包含 Platform、Client、UI 和 file-viewers。
- workspace 全量 `typecheck` 通过：Platform 620 个 strict 文件、Client 1513 个 strict 文件，以及 file-viewers 类型检查。
- Client 生产构建、变更文件架构守卫及 `git diff --check` 通过。
- 本机未构建的可选 canvas 导致初次 Jest 环境启动失败；按 Client 现有规则移开安装目录中的可选链接后，测试正常执行。未修改项目测试配置或依赖声明。

网页部署、真实存储对象、真实账号、Windows/macOS 安装版下载及 PDF 打开验收待执行。HTTP 夹具验证与生产环境验收分别记录。

## Code Review

按仓库 code-review 检查表审查本次 hotfix；范围为附件卡片的地址解析及回归，基线为上述版本。

| 维度 | High | Medium | 结论 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 空路径、历史前缀与编码参数已覆盖 |
| 权限与认证 | 0 | 0 | 复用既有桶代理和签名；服务端认证授权保持原链路 |
| 并发安全 | 0 | 0 | 点击时纯地址解析，沿用下载生命周期 |
| 信息泄漏 | 0 | 0 | 新增夹具使用合成地址和签名；未引入凭据或日志 |
| 测试覆盖 | 0 | 0 | 旧版复现 HTML，修正版验证 PDF 响应 |
| 代码风格 | 0 | 0 | 复用现有解析器，类型及 lint 通过 |
| 文档同步 | 0 | 0 | STATUS 与本记录同步；沿用 hotfix 轻量流程 |

Overall: PASS。发布及真实账号验收按上一节单独执行。
