# 应用删除会话后旧链接读取 — 2026-11-02

## 根因与修复

客户端调用 `DELETE /api/v1/chat/{chat_id}`，服务端将会话行的 `is_delete` 设为 true。消息行保留给现有审计与数据管理流程。历史列表按删除标记过滤，而 `ChatSessionService.get_chat_history()` 只检查会话存在和应用 ID，原账号通过旧链接仍能取得原消息；同一服务的详情读取也会返回该会话。

历史读取现在先检查会话删除状态，已删除会话返回空历史，并在查询消息表前结束。详情读取将已删除会话按缺失会话处理：普通详情返回空值，指定 subject 的访问沿用原有资源不可用处理。应用 ID 校验、正常历史分页及有效分享读取沿用原有逻辑。

本次修改集中于历史与详情的读取语义，数据库继续使用现有软删除方案。

## 基线

- 当前远端 `dataelement/bisheng:feat/bisheng-work-120-main@611fb0f1ac949d3b03fa960cbbc3ff442c0bbfbd`，通过 GitHub 连接器核实。
- 初始本地基线 `de390d4fb` 与远端 `3120e714f` 源码树一致；交付时同步刚合入的附件下载修复，远端基线源码树为 `0d67fdce2d93e3c116eb694bb6138e1d70ca83be`。
- 受影响服务文件在远端的原始 blob 为 `ca73793d99b6ddd17f3a1e6db2606b2fd940748a`，与本地修复前一致。
- 本次工作目录 `.worktrees/bisheng-app-deleted-session-history-20261102`，分支 `codex/app-deleted-session-history`。

## 验证

- 新增 8 项定向回归：原版 4 项失败、4 项通过；修复后 8 项通过。
- 覆盖同账号删除前后刷新旧历史 URL、分享入口读取、已删除详情、正常详情、缺失会话、应用 ID 不匹配及正常历史分页。
- HTTP 测试执行从源码编译的 FastAPI 路由及服务方法，DAO、存储、遥测和历史序列化使用夹具；断言已删除会话在消息查询前结束。
- Ruff 格式与静态检查、受影响服务架构检查、差异检查通过。
- 执行命令：`python -m pytest --noconftest -c src/backend/pyproject.toml src/backend/test/chat_session/test_deleted_session_access.py -q --disable-warnings`。
- 当前本地 Python 环境缺少 `langchain_classic` 等完整服务依赖，既有附件测试在收集阶段受阻。定向测试使用源码方法隔离加载，并保留相同业务分支；完整服务启动、真实数据库、网页部署与真实账号旧链接复测待执行。
