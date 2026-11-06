# Vibe 数据页延迟及繁忙误报修复

## 范围与交付状态

- 日期：2026-10-29。
- 基线：`origin/feat/3.0.0@3eb8f153be8b07b745c7e47ada951e4f40493284`。
- 开发分支：`codex/vibe-data-browse-latency`；独立工作树，未覆盖原 checkout。
- 按现有缺陷修复处理：不新增 API、数据库字段或产品行为；复用既有 16167 三语提示。
- 本记录为提交前完成的代码及定向验证结果；本次交付为 feat/3.0.0 代码修复，未切换 116 正式 manager/helper/前端镜像，116 临时镜像仅供有界只读测量。

## 根因与现场证据

116 示例应用数据页先取表清单，然后并发取 schema 与 rows。每个数据请求都启动独立的短命 helper，manager 同一应用锁为非阻塞。第二个并发请求因此返回 16167，原消息却称“under maintenance”。

现场顺序 API 查询：schema 11.693 秒、rows 11.478 秒，均 HTTP 200 / business 200。并发查询：一个 11.511 秒成功，另一个 0.148 秒返回 business 16167。应用本身 online、发布成功，并非正在维护。

helper 读取 `chat_history` 一行的分段计时（不输出对话、用户字段或凭据）：

| 方案 | CPU 限额 | 总时长 | helper 运行时长 | 说明 |
| --- | --- | --- | --- | --- |
| 原镜像 | 0.1 核 | 12.248 秒 | 11.429 秒 | FastAPI 累计导入约 6.400 秒，appdb 累计约 8.896 秒 |
| 原镜像，仅测量时覆盖 CPU | 1 核 | 1.581 秒 | 1.061 秒 | 用于区分 CPU 启动成本；未修改部署配置 |
| 修复临时镜像 | 0.1 核 | 4.293 秒 | 3.706 秒 | 无 FastAPI 导入；appdb 累计约 2.103 秒 |
| 修复临时镜像，再次测量 | 0.1 核 | 4.490 秒 | 3.816 秒 | 剩余主要为标准库导入与启动成本 |

这些是同一宿主的窄范围样本，带 Python importtime 诊断；不是稳定延迟承诺，也不是浏览器整页耗时。原镜像 Engine create/start/remove 约 0.038/0.451/0.007 秒，主要耗时在容器内启动。

## 修复

1. `errors.py` 直接继承 FastAPI 原本兼容的 Starlette HTTPException，保持 status/detail 信封；observability 捕获同一公共基类。
2. `ExecutionError` 移到轻量独立模块；container_runner 继续导出同一类以兼容现有调用，appdb 直接引用新模块，不再引入编排模块。
3. 页面按现有本地 effect 流程串行读取；schema 成功后才取 rows。同一应用、同一表的 schema 在翻页/排序时复用；切表及显式刷新清除或更新缓存。过期响应丢弃，失败不阻塞后续重试，不缓存业务行。
4. 锁竞争保留 `data_busy`，消息准确描述繁忙；页面用既有 16167 多语言文案，不再直接显示误导性的维护英文。

保留：单应用 DB 挂载、禁网、非 root、只读根、cap-drop、no-new-privileges、128 MiB、100m CPU、最多两个 helper、30 秒期限、owner/租户鉴权与维护互斥。未将 SQLite 读取搬到 manager 主进程。

## 必要定向验证

- 运行时相关文件：原 85 项通过；新增锁竞争测试后，新增文件 4 项通过（相关独立用例累计 86 项）。覆盖 appdb、迁移、helper 隔离与错误清理、观测异常、轻量导入、HTTP 错误信封及 ExecutionError 兼容。
- 前端 `hostedAppDataTab.test.tsx`：16 项通过；覆盖顺序读取、schema 复用/刷新、快速切表旧响应丢弃、失败后重试、繁忙提示、原编辑/导出行为。
- Ruff check/format、改动文件架构守卫、git diff 空白检查：通过。
- 改动前端文件 ESLint：通过。
- 平台 `tsc-strict`：未通过。本机缓存依赖不完整，未改动的 shared chat/file-viewers 缺少 react 等 workspace 链接，shared UI 的 Eye/EyeClose 图标类型也报错；日志在临时目录。不能将此门记为通过；未修改无关代码或扩大测试范围。
- 未运行全量回归；未执行 K8s 性能测试；未做前端部署后的浏览器验收。

## L2 定向自审

按 sdd-code-review 七维度检查：边界、认证、并发、信息泄漏和代码风格无新增发现；设计同步到 F086 §4.9/已知坑。异常 HTTP 基类变更有信封与 observability 测试；旧执行异常 import 保持类身份。helper 启动依赖在新进程中断言，避免 pytest 已导入模块掩盖问题。

状态：**修复及定向测试通过；完整类型门受本机依赖阻塞，正式服务部署及浏览器验证待完成**。不据此宣称线上问题已解决。当前短命容器仍有数秒成本，持续进程/提高 CPU 等进一步路线需要单独评估，不混入本次修复。
