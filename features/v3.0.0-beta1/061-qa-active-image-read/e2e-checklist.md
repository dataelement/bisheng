# E2E 验证清单: 061-qa-active-image-read

**测试环境**: http://localhost:4001/workspace (Client) · 后端 :7860  
**前置条件**:
- 工作台当前问答模型已勾「视觉」
- 至少一份含 markdown 图（`![...](url)`）的知识库 / 知识空间文件 / 频道文章
- MinIO 上对应对象存在（缺对象场景除外）
- 本特性无新 Platform 页面、无新 HTTP 读图 API

**启动**:

```bash
# 后端（src/backend/）
export config=config.yaml
uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log

# Client（src/frontend/）
pnpm --filter bishengchat start -- --host 0.0.0.0
```

---

## Client 前端

### AC-10: 日常模式按需读图

- [ ] 步骤 1: 登录 `/workspace`，打开首页日常对话
- [ ] 步骤 2: 勾选含 markdown 图的知识库
- [ ] 步骤 3: 问「这张图的走势」
- [ ] 预期: 先出现已有 `agent_tool_call`（查看图片 / `view_image`），**不**出现新的读图 UI（AC-18）
- [ ] 预期: 随后答案带原始 `![](url)`，依据画面而不是「看不到图」
- [ ] 验证: 刷新后历史消息仍能渲染原图

### AC-11: 知识空间文件 / 文件夹 / 整空间

- [ ] 步骤 1: 打开知识空间入口，对**含图文件**提问「这张图的走势」
- [ ] 步骤 2: 对**含图文件夹**同样提问
- [ ] 步骤 3: 对**整空间**（`folder_id=0`）同样提问
- [ ] 联调题（`spaceId=1` / `file_id=6`）：「开户申请表单上有哪些字段？」——应读 `img#10` / `img#9` 量级
- [ ] 预期: 首轮若是查看图片，用户侧看不到工具 JSON / tool token（AC-17）
- [ ] 预期: SSE 仍是 `stream`（`content` / `reasoning_content`），**没有** `agent_tool_call` / 工具卡片
- [ ] 预期: 最终答案带原始 `![](url)`，且依据画面

### AC-12: 频道文章问答

- [ ] 步骤 1: 打开 `/workspace/channel/{channelId}/article/{articleId}`（正文含 markdown 图）
- [ ] 步骤 2: 问「这张图的走势」；含图文章也可问「图里写了什么」
- [ ] 预期: 首轮 tool token 不进入答案流（AC-17）
- [ ] 预期: SSE 仍是 `stream`，**没有** `agent_tool_call` / 工具卡片
- [ ] 预期: 最终答案带原始 `![](url)`，且依据画面

### AC-02 / AC-03: 关视觉、无图

- [ ] 步骤: 同一账号把该模型「视觉」关掉，三场景对含图资料再问一次
- [ ] 预期: 不出现查看图片，原文 `![]()` 不变
- [ ] 步骤: 对无 markdown 图的问题提问
- [ ] 预期: 不误调 `view_image`

### AC-15: MinIO 缺对象

- [ ] 步骤: 人为删掉本轮上下文里那张图的 MinIO 对象，再问走势
- [ ] 预期: 会话仍结束，不整轮 500；模型侧收到「该图不可用」

---

## 回归检查

- [ ] 日常 / 知识空间 / 频道相关页正常加载，无 console 错误
- [ ] 无图问答、citation 角标、日常已有附件读图不受影响
- [ ] 灵思任务模式、工作流 / 助手 RAG 未被本 feature 改动
- [ ] 未开视觉的模型仍拒 `image_url`（与今天一致）
