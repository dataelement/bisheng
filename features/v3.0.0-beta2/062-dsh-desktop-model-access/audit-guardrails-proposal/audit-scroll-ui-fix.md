# 会话展开滚动及按钮修复

日期：2026-10-19。分支：feat/3.0.0-dsh-audit，代码基线8d8b5202。用户明确暂缓标题同步，本轮只修改Platform，不修改Desktop、Gateway、服务端、接口、权限、采集或用量。

## 原因及改动

请求卡片的`dt.sr-only`是读屏标签，CSS使用absolute。原卡片没有定位上下文，标签的包含块落到页面，从内部滚动区域溢出并撑大document；外层滚动可以进入没有可见内容的区域。

`ModelAuditCard`根article增加relative，让标签定位在卡片内；保留读屏语义及原有样式，不隐藏整个body滚动、不改全局布局。`ModelAuditTree`和兼容旧后端的`ModelAuditGroup`均删除底部“查看全部已存请求”按钮；会话折叠、分页、请求卡片内的会话跳转和返回仍保留。

## 验证证据

| 检查 | 结果 |
|---|---|
| 修复前定向回归 | 3个新增断言失败：缺relative、树目录及旧平铺仍有全量按钮；其余12项通过 |
| 组件及导航回归 | 5文件30项通过：Card、Tree、Group、Panel、DshPage导航 |
| 审计相关定向回归 | 11文件79项通过：ModelAudit*.test.tsx、auditMessages.test.ts、API/dshModelAudit.test.ts |
| 真实Chromium、合成数据 | 使用真实DshPage/DshManagement/审计组件和项目CSS，复制宿主尺寸布局，Axios adapter只提供合成身份及20条请求，不连接真实业务库 |
| 修复前浏览器复现 | 2048×979视口中展开会话，document.scrollHeight=2476；内部滚动区域仍为821高，20个sr-only标签offsetParent落到页面 |
| 修复后同尺寸 | document.scrollHeight=979、window.scrollY=0；内部列表仍可滚动，所有隐藏标签offsetParent为所属卡片，滚到底后末尾分页可见；全量按钮不存在 |
| 另一桌面尺寸 | 1440×900展开20条请求，document尺寸1440×900、window滚动0；内层滚动到底为1855，末尾分页底边880，视口内可见 |
| 窄屏/减少动态效果 | 375×812触屏模拟、prefers-reduced-motion=reduce中，标签仍绑定所属卡片且全量按钮不存在；合成宿主固定侧栏/六标签有横向溢出，不将此测试表述为完整移动布局验收 |
| 改动文件ESLint | 6个TSX/测试文件通过 |
| 根pnpm typecheck | Platform、Client、file-viewers全部通过；临时浏览器fixture已删除，不留额外严格类型排除 |
| 根pnpm lint | 未通过：6个未改文件的93个既有问题，不能报告全量lint通过；本轮不扩修无关文件 |
| arch-guard / diff --check | 本次6个代码/测试文件通过；无新增库、明文业务数据或凭据 |

组件测试出现既有Input的jsx属性警告及React Router未来版本提示，不是本轮新增失败。浏览器验证不是109部署或真实账号验收；本轮未提交、推送、部署。

临时HTML、TSX和Vite配置仅服务合成验证，已删除；本轮启动的本机3001/3002进程已停止，不清理其他用户文件或进程。

## 代码增量审查

按code-review七维度检查HEAD到本次6个代码/测试文件的工作区差异，不把未实施的标题候选文档算作已交付代码。

| 维度 | 结论 |
|---|---|
| 边界 | 保留空列表、分页、深层继续查看及正文按需读取；relative不改变卡片在文档流中的尺寸 |
| 权限及认证 | 没有改动；移除按钮不增加任何数据访问范围 |
| 并发安全 | 没有新增状态、请求或异步路径；旧响应隔离继续由现有hook负责 |
| 信息泄漏 | 仅样式定位及按钮移除；不暴露正文或真实测试数据 |
| 测试 | 新断言先失败后通过，配合真实浏览器DOM几何核验，不用jsdom证明真实布局 |
| 风格 | 复用现有设计、保留无障碍标签，无新组件/库；改动文件lint及整体类型检查通过 |
| 文档 | design已记录隐藏标签的包含块陷阱及当前按钮行为；标题候选明确暂缓，未混入业务实现 |

本次增量审查无high/medium问题；全量既有lint失败及未部署边界仍如实保留。
