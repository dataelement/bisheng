# 前端依赖治理验证与验收

2026-10-22；分支 `codex/frontend-dependency-cleanup`，基线 `6331d7cfc`。开发及技术验证完成，未合并、未推送。执行计划见 [implementation plan](2026-10-22-frontend-dependency-cleanup.md)。

## 已完成

- 两端列表排序切换到 catalog 固定的 `@hello-pangea/dnd@18.0.1`，移除 `react-beautiful-dnd`；保留原业务 ID、保存接口和提交时机。
- 删除不可达的 Mention / PromptsCommand / TaggingSheet 及失效引用，移除 `react-virtualized` 和 `@types/axios`。
- 两端 `react-window` 统一通过 catalog 固定 1.8.11；实际使用中的 `react-dnd` 与 `react-color` 保留。旧上传拖拽监听没有重新接入。
- 补齐必要占位元素；取消或原位置放下不误保存。推荐应用限制提示补齐三语言。
- 锁文件保留既有 SheetJS 0.20.3 SHA-512，增加防丢失回归检查。未升级无关依赖。

## 技术验证

| 检查 | 结果 |
| --- | --- |
| workspace 配置与依赖契约 | 30 项通过，含 SheetJS 校验值 |
| platform 排序、文件预览、语音、看板配色回归 | 35 项通过，单 worker |
| client 分类排序、文件类型和输入、共享会话回归 | 24 项通过，单进程 |
| i18n / 配置类型检查 / architecture guard / diff 空白检查 | 通过 |
| 修改文件 ESLint | 通过；生成的 suppression 仅减少 |
| 冻结离线锁文件安装验证 | 7 个 workspace 项目通过（临时目录，lockfile-only） |
| platform / client 生产构建 | 均通过，串行执行 |
| 独立 review | PASS；发现的 SheetJS 校验值丢失问题已修复并经 RED/GREEN 验证 |

完整 lint / typecheck 仍有既存基线问题，不能称为全绿：platform lint 85 errors，client lint 119 errors / 2 warnings；platform 类型 1 处（clientVoiceDraft 测试参数），client 类型 7 处（skillCenter / useSkillCenter / SpeechToText 测试）。与执行前一致，无新增 suppression 或 strict-ignore。

client 的三个 node 环境旧测试首次被全局 DOM setup 阻挡（Element 未定义）；复跑时仅对这三个纯逻辑测试移除 DOM setup，12 项通过，仓库测试配置未修改。

### 浏览器验证边界

使用真实业务组件、原有编译样式、隔离 API 数据，未修改测试环境业务数据。8 类排序均完成鼠标和键盘检查：工作流选项、工具、组织知识库、推荐应用、切分规则、变量、模板、客户端分类。

重点通过：工作流排序后继续编辑及重载；模板顺序保存载荷和重载；真实变量弹窗；客户端真实弹窗和 body portal；Esc 取消后恢复顺序与焦点并能继续排序保存；20 项工具列表滚动到底部后排序，默认选中状态保留。浏览器未记录排序运行时错误。

生产静态启动：platform 显示登录控件；client 加载主入口后等待配置接口。静态服务缺少后端，出现预期 404；未见 HighlightJS 初始化或 Provider 异常。此检查不代表业务联调通过。临时服务和浏览器页均已关闭。

### 产物体积

相同口径：递归汇总各端 `build/assets` 内 `.js` / `.css`，逐文件 gzip 后求和；不包括外置静态资源。

| 应用 | 调整前 gzip | 调整后 gzip | 差异 |
| --- | ---: | ---: | ---: |
| platform | 3,232,137 B | 3,230,231 B | -1,906 B |
| client | 2,519,365 B | 2,519,178 B | -187 B |

本轮主要收益是维护性和清除失效依赖，产物体积基本持平。

## 真实业务环境验收（待执行）

每行按业务模块验收，保存后刷新或退出再进入，核对顺序和项目内容。

- [ ] 工作流：输入/输出节点多选项排序，编辑、删除后保存再打开；取消拖动无误保存。
- [ ] 工作台：工具、组织知识库、推荐应用分别排序；默认项状态和刷新顺序正确；长列表滚动正常。
- [ ] 知识库：多条切分规则排序后编辑、保存，规则表达式和切分位置保持一致。
- [ ] 变量与模板：变量调整后取消不落库、保存生效；模板排序刷新后保持。
- [ ] 客户端分类：真实弹窗鼠标及键盘排序，Esc 取消后继续操作，取消无落库，保存后导航顺序正确。
- [ ] 关联回归：工作流画布拖动/缩放、代码编辑、一次拖入仅上传一次、文件预览长列表、收藏拖拽、主题/看板配色。

以上业务验收完成后，再由用户决定合并和推送；不自动同步 release。
