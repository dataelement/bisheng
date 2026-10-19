# 桌面统一导航接缝

2026-10-19。网页基线 feat/bisheng-work-120 4269304db；桌面基线 bisheng-work/V1.2.0 e9f2063。

MainLayout 持有 DesktopShellBridge，在桌面嵌入时将 useSidebarEntries 产生的实际菜单、名称、选中项和 splitSidebarEntries 的主菜单归属上报给宿主。平台权限、菜单配置与技能中心预览开关继续由既有网页逻辑决定。宿主提供与 Work 共用的桌面导航；知识空间、订阅、应用、技能与广场内容沿用现有页面。网页独立访问沿用 WorkbenchSidebar。

路由与主题桥接由 MainLayout 单次挂载，支持明确的聊天与功能首页路径；页面内部子路由仍由网页管理。远程展示桥只输出菜单状态，企业凭据与本地执行能力由宿主分别持有。Work 的本地项目和任务维持原有存储及执行方式。

验证：网页生产构建、strict typecheck 与修改文件 lint 通过；导航路径、主题与会话呈现回归通过。3006 与原生窗口的最终验证见根项目交付记录。
