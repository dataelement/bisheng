# Tasks: 会话上传文件永久化 + 对话图片展示

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户已确认（存量不可恢复 / 会话删除即清理 / 按需换发链接 / 三场景一并处理 / 对象名唯一化纳入范围） |
| design.md | ✅ 已评审 | 用户已确认；接手时第一入口 |
| tasks.md | 🔲 草稿 | 待用户确认 |
| 实现 | 🔲 未开始 | 0 / 11 完成 |

---

## 开发模式

- 后端 Test-First：对象名生成与换发鉴权都是纯逻辑，可单测覆盖；MinIO 交互 mock 掉。
- 前端手动验证（Playwright 🚧 未落地）。
- **顺序要求**：Wave 1（存储基建）→ Wave 2（三个上传入口）→ Wave 3（换发 + 清理）→ Wave 4（前端）。Wave 2 的三个入口彼此独立，可并行。

---

## Tasks

### Wave 1 — 存储层基建

- [ ] **T001**: 会话附件对象名生成 + 单元测试
  **文件**: `src/backend/bisheng/core/storage/chat_attachment.py`（新建，或就近放入既有存储工具模块）
  `src/backend/test/core/test_chat_attachment_object_name.py`（新建）
  **逻辑**: 纯函数 `build_chat_object_name(user_id, filename) -> str` → `chat/{user_id}/{uuid}{ext}`。扩展名从原文件名取并小写化；无扩展名时不加；文件名中的路径分隔符与 `..` 必须被丢弃（对象名不得由用户内容拼出目录穿越）
  **测试**: 同名文件两次调用得到不同对象名；扩展名保留且小写；无扩展名；文件名含 `../` 与 `/`；超长文件名
  **覆盖 AC**: AC-02
  **依赖**: 无

- [ ] **T002**: 存储层补「按前缀列举 / 批量删除」
  **文件**: `src/backend/bisheng/core/storage/minio/minio_storage.py`
  **逻辑**: 新增 `list_objects(bucket, prefix)` 与 `remove_objects_by_prefix(bucket, prefix)`（底层 minio SDK 原生支持 `list_objects(recursive=True)`）。删除需容忍单个对象失败并继续，返回成功/失败计数
  **约束**: 前缀为空或仅 `/` 时必须直接拒绝（防止误删整桶）
  **覆盖 AC**: AC-03
  **依赖**: 无

### Wave 2 — 三个上传入口改为永久存储（可并行）

> 三处都改成：显式指定主桶 + 用 T001 生成对象名 + 把**对象名**随上传结果回传（前端发消息时带回，最终落进消息的 files 结构）。
> ⚠️ `save_uploaded_file()` 的 `bucket_name` 参数所有调用方都没传、默认落临时桶（design §5 坑 3）——改造时必须显式传参。

- [ ] **T003**: 日常模式上传入口
  **文件**: `src/backend/bisheng/workstation/api/endpoints/knowledge.py`（`POST /files`）
  **逻辑**: 当前对象名是 `unquote(file.filename)`（**原始文件名，无唯一化 —— 本特性要修的数据泄露根因**，design §5 坑 2）。改为 T001 生成；落主桶；响应新增对象名字段
  **覆盖 AC**: AC-01, AC-02
  **依赖**: T001

- [ ] **T004**: 工作流会话上传入口（**另开专用入口**）
  **文件**: 会话上传新端点（`bisheng/chat_session/api/endpoints/chat.py` 或同模块）
  **逻辑**: 已查明 `POST /knowledge/upload` 被 API 接入示例、知识库 QA 导入、数据集创建等多处共用（design §5 坑 9），**不改它**；为会话新增专用上传端点：主桶 + T001 对象名，响应带对象名。client 端 `uploadChatFile` 无 mode 分支改指向新端点
  **覆盖 AC**: AC-01
  **依赖**: T001

- [ ] **T005**: 任务模式（灵思）上传入口
  **文件**: `src/backend/bisheng/linsight/domain/services/workbench_impl.py` / `bisheng/linsight/domain/utils.py`
  **逻辑**: 已落主桶（永久），仅需统一对象名为 T001 规则并回传对象名，使三场景一致
  **覆盖 AC**: AC-01, AC-11
  **依赖**: T001

### Wave 3 — 换发链接与清理

- [ ] **T006**: 换发链接的鉴权逻辑 + 单元测试
  **文件**: `src/backend/bisheng/chat_session/domain/chat.py`（或同模块 service）
  `src/backend/test/chat_session/test_attachment_link.py`（新建）
  **逻辑**: `resolve_attachment_url(chat_id, file_id, login_user)` —— ①载入会话 ②校验请求者为会话所属用户 ③在该会话消息的 files 中查 `file_id` 取**对象名** ④签发短时效链接。**对象名只从服务端数据取，绝不使用入参**（design §3 决策 3、§5 坑 6）
  **测试**: 非所属用户 → 拒绝；file_id 不存在 → 拒绝；会话不存在 → 拒绝；正常 → 返回链接；**入参伪造对象名不影响结果**
  **覆盖 AC**: AC-04, AC-08
  **依赖**: 无

- [ ] **T007**: 换发链接端点
  **文件**: `src/backend/bisheng/chat_session/api/endpoints/chat.py`
  **逻辑**: 新增端点，入参 `chat_id` + `file_id`，委托 T006；不新增错误码，复用既有未授权 / 未找到响应
  **覆盖 AC**: AC-04, AC-08
  **依赖**: T006

- [ ] **T008**: 会话删除时清理附件
  **文件**: `src/backend/bisheng/chat_session/domain/chat.py`（`delete_session`）
  **逻辑**: 软删会话后，从该会话的消息 files 中取出对象名并逐个删除（上传时拿不到会话 ID，无法按前缀清扫——design §5 坑 8）。T002 的前缀删除保留给未来按用户清理 / 巡检使用。**清理失败只记日志，不得让删除会话失败**（spec §3）
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
- T004 偏离：改为新增会话专用上传端点，不改共用的 `/knowledge/upload` → 新增坑 9（该接口被知识库/数据集/API 示例共用）
- T008 偏离：删除改为「从消息取对象名逐个删」，不再按前缀清扫（同坑 8）
