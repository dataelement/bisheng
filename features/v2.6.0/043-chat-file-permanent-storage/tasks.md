# Tasks: 会话上传文件永久化 + 对话图片展示

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户已确认（存量不可恢复 / 会话删除即清理 / 按需换发链接 / 三场景一并处理 / 对象名唯一化纳入范围） |
| design.md | ✅ 已评审 | 用户已确认；接手时第一入口 |
| tasks.md | ✅ 已拆解 | 方案调整后重排波次 |
| 实现 | 🟡 进行中 | 2 / 13 完成（Wave 1 已完成）|

---

## 开发模式

- 后端 Test-First：对象名生成与换发鉴权都是纯逻辑，可单测覆盖；MinIO 交互 mock 掉。
- 前端手动验证（Playwright 🚧 未落地）。
- **顺序要求**：Wave 1（存储基建）→ Wave 2（三个上传入口）→ Wave 3（换发 + 清理）→ Wave 4（前端）。Wave 2 的三个入口彼此独立，可并行。

---

## Tasks

### Wave 1 — 存储层基建

- [x] **T001**: 会话附件对象名生成 + 单元测试
  **文件**: `src/backend/bisheng/core/storage/chat_attachment.py`、`test/core/test_chat_attachment_object_name.py`
  **逻辑**: `build_chat_object_name(user_id, filename)` → `chat/{user_id}/{uuid}{ext}`。只从用户文件名取扩展名；路径分隔符与 `..` 一律丢弃；对象名必须纯 ASCII（design §5 坑 10）
  **覆盖 AC**: AC-02
  **依赖**: 无

- [x] **T002**: 附件「转正」逻辑 + 单元测试
  **文件**: `src/backend/bisheng/core/storage/chat_attachment.py`、`test/core/test_promote_chat_attachments.py`
  **逻辑**: `promote_chat_attachments(files, user_id)` —— 从上传时签发的链接反解临时对象名 → 服务端 copy 到主桶 → 把永久对象名写回 files。**已有 object_name 的跳过**（任务模式本就落主桶）；**单个失败不影响其他附件与消息本身**
  **覆盖 AC**: AC-01, AC-02
  **依赖**: T001

### Wave 2 — 在消息落库处接入转正（4 处）

> 上传接口**一个都不改**（design 决策 1 选 B）。日常模式前端改用共用上传接口即可获得 uuid 命名。

- [ ] **T003**: 日常模式消息落库接入
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`（两处 `files=json.dumps(data.files)`）
  **逻辑**: 存库前调 `promote_chat_attachments(data.files, login_user.user_id)`
  **覆盖 AC**: AC-01
  **依赖**: T002

- [ ] **T004**: 工作流会话消息落库接入
  **文件**: `src/backend/bisheng/worker/workflow/redis_callback.py`（`files=json.dumps(chat_response.files…)`）
  **逻辑**: 同上；注意此处在 Celery worker 内，需确认用户上下文可取
  **覆盖 AC**: AC-01
  **依赖**: T002

- [ ] **T005**: 任务模式消息落库确认
  **文件**: `src/backend/bisheng/linsight/domain/utils.py`（`files=json.dumps(files)`）
  **逻辑**: 灵思上传已落主桶。**只需确认消息 files 里带了对象名**（其上传处写的是 `file_info["file_url"] = object_name`）；带了则接入 `promote_chat_attachments` 后会自动跳过 copy，不带则补上字段
  **覆盖 AC**: AC-01, AC-11
  **依赖**: T002

- [ ] **T006**: 日常模式前端改用共用上传接口
  **文件**: `src/frontend/client/src/api/apps.ts`（`uploadChatFile` 的 `urlMap`）
  **逻辑**: 日常模式不再指向 `/workstation/files`，改用 `/api/v1/knowledge/upload`（已 uuid 命名，**同名覆盖泄露随之消失**）。前端字段已有兜底（`file_id` 回落本地 id、`parsing_status` 有默认值），无需额外适配
  **覆盖 AC**: AC-02
  **依赖**: 无

### Wave 3 — 换发链接与清理

- [ ] **T007**: 换发链接的鉴权逻辑 + 单元测试
  **文件**: `src/backend/bisheng/chat_session/domain/chat.py`（或同模块 service）
  `src/backend/test/chat_session/test_attachment_link.py`（新建）
  **逻辑**: `resolve_attachment_url(chat_id, file_id, login_user)` —— ①载入会话 ②校验请求者为会话所属用户 ③在该会话消息的 files 中查 `file_id` 取**对象名** ④签发短时效链接。**对象名只从服务端数据取，绝不使用入参**（design §3 决策 3、§5 坑 6）
  **测试**: 非所属用户 → 拒绝；file_id 不存在 → 拒绝；会话不存在 → 拒绝；正常 → 返回链接；**入参伪造对象名不影响结果**
  **覆盖 AC**: AC-04, AC-08
  **依赖**: 无

- [ ] **T008**: 换发链接端点
  **文件**: `src/backend/bisheng/chat_session/api/endpoints/chat.py`
  **逻辑**: 新增端点，入参 `chat_id` + `file_id`，委托 T007；不新增错误码，复用既有未授权 / 未找到响应
  **覆盖 AC**: AC-04, AC-08
  **依赖**: T006

- [ ] **T009**: 会话删除时清理附件
  **文件**: `src/backend/bisheng/chat_session/domain/chat.py`（`delete_session`）
  **逻辑**: 软删会话后，从该会话的消息 files 中取出 `object_name` 并逐个删除（上传时拿不到会话 ID，无法按前缀清扫——design §5 坑 8）。**清理失败只记日志，不得让删除会话失败**（spec §3）
  **覆盖 AC**: AC-03
  **依赖**: T002

### Wave 4 — 前端（client）

- [ ] **T009**: 共用「消息图片」组件 + 换发链接接入
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/MessageImage.tsx`（新建，基于既有 `Image.tsx` / `DialogImage.tsx` 提取）
  `src/frontend/client/src/api/chatApi.ts`（新增换发链接请求方法）
  **逻辑**: 渲染时调换发接口取链接 → 缩略图 → 点击全屏（右上角关闭）；**换发失败或图片加载失败** → 渲染占位「图片已失效，无法查看」（design §3 决策 4）；老消息无对象名字段时直接走失效分支（向后兼容）
  **覆盖 AC**: AC-06, AC-07, AC-08, AC-09
  **依赖**: T007

- [ ] **T010**: 两套消息渲染各自接入
  **文件**: `src/frontend/client/src/components/Chat/AiMessageBubble.tsx`（日常 / 任务模式）
  `src/frontend/client/src/pages/appChat/components/MessageFile.tsx` / `ChatFile.tsx`（工作流会话）
  **逻辑**: 按文件名后缀分流（png/jpg/jpeg/gif/webp/bmp/svg → 图片组件，其余保持现状）。**这是两套独立渲染，必须都改**（design §5 坑 7）；文件名字段各入口键名不一，取值做兼容
  **覆盖 AC**: AC-05, AC-10, AC-11
  **依赖**: T009

- [ ] **T011**: 失效占位文案 i18n
  **文件**: `src/frontend/client/src/locales/{en,zh-Hans,ja}/translation.json`
  **逻辑**: 「图片已失效，无法查看」三语（嵌套命名空间）
  **⚠️ 前车之鉴**: F044 曾把文案加错命名空间导致不生效——加完确认页面 `t()` 实际读的是哪个命名空间
  **覆盖 AC**: AC-09
  **依赖**: T009

---

## 手动验证清单（全部完成后按序跑）

1. **两个不同用户各上传同名 `1.png`** → 各自会话里看到的都是自己那张（AC-02，**最关键**，验证数据泄露已修）
2. 三个场景各传一张图 → 缩略图 → 点开全屏 → 右上角关闭（AC-05/06/07/11）
3. 传一个非图片附件 → 展示与改动前一致（AC-10）
4. 删除一个含附件的会话 → 该会话消息中记录的对象在存储中应已消失（AC-03）
5. 用另一个账号调换发接口请求他人会话的附件 → 应被拒绝（AC-04）
6. 打开一个存量老会话 → 图片显示「图片已失效，无法查看」（预期行为，非缺陷）
7. 切 en / ja 检查新增文案（AC-09）

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时先停下重新确认。

- T001 偏离：对象名由 `chat/{chat_id}/` 改为 `chat/{user_id}/` → 更新 design 决策 1 + 新增坑 8（上传发生在会话创建之前，命名时拿不到会话 ID）
- 方案整体调整：由「上传即落主桶」改为「上传不动 + 发消息时转正」→ 更新 design 决策 1（用户提出应避免改共用上传接口，顺此消除孤儿文件问题）
- 原 T002「前缀批量删除」已移除：新方案下删除按对象名进行，该能力无调用方，不留投机性死代码
- T008 偏离：删除改为「从消息取对象名逐个删」，不再按前缀清扫（同坑 8）
