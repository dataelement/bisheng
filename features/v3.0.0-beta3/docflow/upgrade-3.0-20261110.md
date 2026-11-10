# zhgyl 升级至主版 3.0

日期：2026-11-10。目标分支：`feat/zhgyl-3.0-beat1`。

## 升级范围

先将目标分支快进至远端 `6dd6cd874`，再合入主版 `feat/3.0.0` 的 `45bbfe2e8`。
主版以正式 3.0 的代码和结构为准；保留目标分支的 DocFlow OCR、ZIP 上传、安全报告 5.2–5.5 修复及部署前缀。
定制文件核对基线为原主版 beta3 `05941384f` 到目标 `6dd6cd874` 的 103 个文件。
唯一移除的旧定制文件是主版已废弃、已无调用的客户端 `components/PreviewFile/index.tsx`，相应 DocFlow 能力迁入现有预览入口。

## 合并中的兼容处理

- DocFlow 配置、租户任务登记、解析租约、结构分段、缓存隔离与双索引检查点全部保留。
- 正式/临时知识库引用在出参边界转换 DocFlow 页码，保留原索引 1-based 坐标；`bbox.page_base` 防止重复转换。
  未标记来源的历史临时引用保持旧规则，不通过数值猜测来源。已完成 Milvus 写入的旧检查点仍可仅补写 ES。
- ZIP 的上传端点、manifest、属主/租户守卫、工作流/任务/日常消费链路保留。
  主版共享表单增加独立提交锁，上传回写不受影响；修复删除完成附件提前解锁与失败重复计数，已删除的排队请求不会发出。
- ZIP 错误码迁至 `10994`，保留主版租户变化错误码 `10993`；三语源文件合并后重新生成两套前端产物。
- 主版共享代理/环境加载与定制 `VITE_BASE_URL` 同时保留，workspace、SSO、个人令牌安装链接及静态资源继续使用部署前缀。
- 前端沿用主版 UI 和共享预览；上传组件按项目 600 行限制拆分，未改变视觉或交互设计。
- 权限模型采用主版 `f048-v6-app`，重新生成性能基准模型/合同 checksum，未增加定制授权关系。

## 验证方式与边界

后端使用现有 `.venv`；需要配置的测试使用仅含本地 SQLite/Redis 假地址的临时配置，不提交配置或凭据。

定制自包含回归命令（`src/backend`）：

```bash
config=<isolated-test-config> .venv/bin/python -m pytest --noconftest -q \
  test/knowledge/docflow test/knowledge/test_archive_validation.py \
  test/security/test_report_52_55.py test/knowledge/rag/test_splitter_hard_limit.py \
  test/database/test_alembic_single_head.py
config=<isolated-test-config> .venv/bin/python -m pytest --noconftest -q \
  test/knowledge/test_archive_upload_service.py
```

另运行 citation 全套与工作流、日常附件、文件生命周期、权限模型及 MinerU/OFD 兼容组合回归。
Python 语法、冲突标记、修改过的 JSON 重复键及差异空白单独检查。
定制增量架构守卫仍报告两侧已有的 `chat.py` 跨模块 API 导入及既有警告，本次未新增该类导入。

最终本地结果：

- citation 全套及工作流/日常附件/权限/解析组合：474 passed。
- DocFlow、ZIP 校验、安全报告、分段硬限制及迁移单头自包含组合：103 passed，8 subtests passed。
- ZIP 上传服务：8 passed。
- 合计 585 项通过，另有 8 项子测试；仅有依赖弃用警告，无失败或错误。
- 1902 个新增/修改 Python 文件语法通过；77 个新增/修改前端 JSON 无语法错误或重复键；未发现残留冲突标记。
  相对主版的定制/冲突处理增量空白检查通过；主版既有空白问题保留，命中的文件均与主版完全一致。
- `alembic heads`：单一 `f114_app_authorization`；新引用兼容代码及回归测试的定向 Ruff 检查通过。
- 合并前再次 fetch，远端 zhgyl 与主版 tip 仍分别为 `6dd6cd874`、`45bbfe2e8`。

前端测试、lint/typecheck、生产构建按用户约定留给镜像构建阶段，不能视作本地已通过。
真实 DocFlow/MK、中间件、双数据库、SSO、浏览器和部署前缀验收仍须在目标环境执行。
此前 DocFlow 验证记录中的既有未完成事项保持不变，本次合并不宣称补齐。

## 部署要求

- 数据库迁移头应为单一 `f114_app_authorization`。
- 权限模型从 `f048-v5` 升级为 `f048-v6-app`。部署时必须按发布流程执行
  `scripts/publish_authorization_model_change.py` 的 dry-run/apply；不能仅重启或使用 `force_write_model`。
- API 与所有解析 Worker 使用相同的后端版本；保持客户已有的 DocFlow 配置和部署前缀。
- 本记录只描述代码升级，不代表已推送或部署运行环境。
