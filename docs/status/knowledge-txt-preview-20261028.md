# 知识空间搜索结果 TXT 正文预览复核

日期：2026-10-28

## 根因与修复

macOS Chrome 在 13001 知识空间 11 搜索“权限验收”，打开命中的“权限验收.txt”（file/6），复现应用首页 HTML 源码占据正文。预览接口返回 `/bisheng/original/6.txt` 与签名查询参数，`preview_url` 为空。

相同签名的响应对照：

| 路径 | HTTP | Content-Type | 响应长度 | 内容 |
| --- | --- | --- | --- | --- |
| `/bisheng/original/6.txt` | 200 | application/octet-stream | 107 字节 | 实际 TXT 正文 |
| `/workspace/bisheng/original/6.txt` | 200 | text/html | 4494 字节 | 应用首页 HTML |

根因是文件资源错误进入 SPA 页面路径。PR [#2535](https://github.com/dataelement/bisheng/pull/2535) 的共享地址解析修复已覆盖该 TXT 路由；合并提交为 `e83fad4b8f3f9081e0d68a071402ecf5217e9a87`。复核沿用这项根因修复，文本查看器继续原样呈现文件内容。本轮新增正文加载回归测试。

## 基线与验证

- 远端发布分支：`dataelement/bisheng:feat/bisheng-work-120-main@fd6c95ca1b7986c60ea72d16d896a3de0ed4e9c2`，由远端读取确认，包含 #2535。
- 工作目录：`.worktrees/bisheng-knowledge-txt-preview`；分支：`codex/knowledge-txt-preview`。本轮修改范围为 BISHENG Client 测试与证据文档，运行时代码沿用发布分支。
- 新增 5 项回归：从搜索结果使用的预览路由，经预览 API 数据、实际地址解析函数及真实 TextViewer，验证根路径、历史页面前缀、重复前缀、绝对存储 URL 和优先预览地址均加载 TXT 正文；签名、中文、换行与文本中的 HTML 字面量保持原样。
- 测试夹具模拟真实代理行为：错误路径返回 HTTP 200 应用 HTML。换回 #2535 之前的解析函数，5 项全部失败；恢复当前解析函数后，相关 3 组共 33 项通过。
- 客户端全量 ESLint、1485 个严格类型文件检查、架构守卫及差异检查通过。依赖沿用已有工作区安装；Jest 使用其 pnpm 模块路径。
- macOS Chrome 本地组件验证：使用真实 file/6 的 107 字节正文、发布分支的解析函数和 TextViewer，页面成功显示正文。验证页面使用独立布局，文件响应来自本机下载副本。
- 回归提交：[PR #2538](https://github.com/dataelement/bisheng/pull/2538)。提交期间目标分支合入频道导航修复 #2536，本分支已同步 `1a8ac45e1d58a6f0bde7f0fe13552f2beb7b46a1`；组合后的 4 组 / 42 项回归、客户端全量 ESLint 与 1486 个严格类型文件检查通过。

## 发布与验收边界

13001 在本轮实测时仍请求旧路径并呈现 HTML；该环境需要部署包含 #2535 的 Client 后，重新执行“搜索 → 打开 TXT → 正文显示”的完整验收。源码修复已合并，真实文件的本地组件验证已通过，13001 部署后验收与 Safari 验收待执行。

本机证据：主工作区 `outputs/knowledge-txt-preview-20261028/`，含 `tests.log`、`old-routing-regression.log`、`lint.log`、`typecheck.log` 与 `txt-preview.png`。访问凭据和签名 URL 保存在证据范围之外。
