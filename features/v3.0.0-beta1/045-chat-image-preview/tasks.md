# Tasks: 支持展示对话中上传的图片

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户已确认 |
| design.md | ✅ 已评审 | 用户已确认；接手时第一入口 |
| tasks.md | 🔲 草稿 | 待用户确认 |
| 实现 | 🔲 未开始 | 0 / 6 完成 |

---

## 开发模式

- **纯前端（client）**，零后端改动、零接口新增。
- 手动验证为主；图片识别的纯函数补组件级测试。
- 遵循 client AGENTS.md：`~/` 别名、命名导出、单文件 ≤600 行、图标优先 `bisheng-icons`、不引入新 UI 库。

---

## Tasks

### Wave 1 — 共用件

- [ ] **T001**: 图片识别工具函数 + 测试
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/`（或就近共用工具位置）
  **逻辑**: `isImageFile(fileName: string): boolean`——按**文件名后缀**判断（`png/jpg/jpeg/gif/webp/bmp/svg`），大小写不敏感；复用既有取后缀工具（`getFileTypebyFileName`），保持与文件图标同一口径。**不看 MIME 字段**（存量消息不保证有——design §3 决策 1、§5 坑 4）
  **测试**: 大写后缀、无后缀、多点文件名、空文件名各一例
  **覆盖 AC**: AC-01, AC-05
  **依赖**: 无

- [ ] **T002**: 共用「消息图片」组件
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/MessageImage.tsx`（新建）
  基于既有 `Image.tsx`（懒加载）与 `DialogImage.tsx`（全屏查看）提取复用，不新写 lightbox、不引新依赖
  **逻辑**: 渲染缩略图 → 点击开全屏（右上角关闭）；**加载失败 → 渲染占位「图片已失效，无法查看」**（design §3 决策 3、§5 坑 5）；渲染前把地址的 host 段替换为当前环境地址（沿用既有做法，§5 坑 3）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04
  **依赖**: T001

- [ ] **T003**: 失效占位文案 i18n
  **文件**: `src/frontend/client/src/locales/{en,zh-Hans,ja}/translation.json`
  **逻辑**: 新增「图片已失效，无法查看」三语键（嵌套命名空间）
  **依赖**: T002

### Wave 2 — 两套消息渲染各自接入

- [ ] **T004**: 日常模式 / 任务模式接入
  **文件**: `src/frontend/client/src/components/Chat/AiMessageBubble.tsx`（内部 `UploadedFileList`）
  **逻辑**: 附件列表按 `isImageFile` 分流——图片渲染 `MessageImage`，其余保持现状的"图标 + 文件名"行**完全不变**。注意文件名字段在不同入口键名不一（`name` / `file_name`），取值做兼容（design §5 坑 4）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-06
  **手动验证**（日常模式 + 任务模式各一遍）:
  - 传 png 发送 → 显示缩略图 → 点开全屏 → 关闭
  - 传 pdf → 仍是文件行（无回归）
  - 一条消息传 2 张图 → 各自可独立放大
  - 打开升级前发过图的历史会话 → 同样显示缩略图（AC-05）
  **依赖**: T002

- [ ] **T005**: 工作流会话接入
  **文件**: `src/frontend/client/src/pages/appChat/components/MessageFile.tsx` / `ChatFile.tsx`
  **逻辑**: 同样按 `isImageFile` 分流——图片渲染 `MessageImage`，非图片保持现状的"点击下载"卡片不变。**这是另一套独立的消息渲染，必须单独改**（design §5 坑 1）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-06, AC-07
  **手动验证**: 工作流会话传图 → 缩略图 + 全屏；传非图片 → 下载卡片不变；与日常模式对比视觉一致（AC-07）
  **依赖**: T002

### Wave 3 — 失效路径验证

- [ ] **T006**: 失效占位跨场景验证
  **文件**: 仅验证，不改代码
  **逻辑**: 统一验证两套渲染的失效表现一致
  **覆盖 AC**: AC-04, AC-07
  **手动验证**: 手动把某条消息的图片地址改坏（或打开 7 天前的历史会话）→ 两个场景均显示「图片已失效，无法查看」，控制台无未捕获报错，**不出现浏览器裂图**
  **依赖**: T004, T005

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。

- （待填）
