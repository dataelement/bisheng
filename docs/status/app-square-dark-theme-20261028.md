# 发现广场应用卡片暗色修复

- 根因：应用卡片的渐变中心与操作遮罩使用固定白色；桌面既有广场渐变适配识别十六进制色值，应用卡片使用 RGB 写法。
- 修复：AgentCard 统一使用主题表面变量，暗色取 `--fill-1`，浅色取 `--bg-page`；暗色渐变沿用知识空间的 8% 品牌色。简介使用语义文字颜色，操作遮罩、标签淡出和窄屏按钮使用同一表面变量。精选标签同步三语言并清理对应旧 lint 豁免。
- 验证：Client / Platform / UI / File Viewers lint、Client 1,491 个严格类型文件、Platform 619 个严格类型文件、File Viewers 类型检查、Client 生产构建、i18n 检查通过；分享权限 3 项既有回归通过。macOS Electron 使用实际 AgentCard、共享 Button、生成的 Client CSS 和桌面主题适配代码，12 组宽度／品牌色／浅色与网页暗色及桌面暗色检查通过。
- 基线：已同步远端 `dataelement/bisheng:feat/bisheng-work-120-main@d3d832a0e0f8299e2497734e7b72da6072c13937`，组合代码再次通过 Client / Platform lint、类型检查、Client 构建、i18n、3 项回归与 12 组组件渲染验证。目录 `.worktrees/bisheng-app-square-dark-theme`，分支 `codex/app-square-dark-theme`。
- 交付边界：本地源码修复与组件验证完成。PR 交付目标为 `dataelement/bisheng:feat/bisheng-work-120-main`；代码发布、13001 真实账号及 Windows 验收待执行；发布位置为毕昇 Client 网页资源。组件验证的账号数据、权限服务和头像使用夹具。
- 证据：工作区 `outputs/app-square-dark-theme-20261028/`，含 12 张渲染截图、计算样式、点击检查与构建日志。
