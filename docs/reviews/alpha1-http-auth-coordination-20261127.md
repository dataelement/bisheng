# alpha1 HTTP 会话协调兼容修复

2026-11-27，基线 `7f665b1704`。部署验收发现，通过 HTTP 访问非 localhost 地址时没有 Web Locks 和 `crypto.randomUUID()`，会话协调的 IndexedDB 分支在发出认证请求前失败，页面显示认证暂不可用。

复用项目已用于对话、附件和移动操作的 `uuid` 包 `v4`，替换两处原生 `crypto.randomUUID()`：租约 owner 和无 BroadcastChannel 时的通知 nonce。检查过现用版本的浏览器实现：没有原生 randomUUID 时使用 `crypto.getRandomValues()`。没有新增随机数生成器、Math.random 降级或绕过跨标签会话锁。

将 uuid 版本纳入工作区 catalog；客户端和共享 API 包共同引用，锁定版本仍为已有的 11.1.1。

验证：共享包 85 项测试通过，包含没有原生 randomUUID 时的 IndexedDB 互斥；共享包 lint/typecheck、Client/Platform 全量严格类型检查、隔离目录 frozen lockfile 校验及 diff 检查通过。发布后的 HTTP 页面验收另记部署记录。

Hotfix review：边界、权限、并发、信息泄漏、测试、风格、文档七个维度均 PASS。会话 ID、凭据、租约续期和 fencing 协议没有改变。

## 部署验收补充：匿名启动

UUID 修复部署后，HTTP 浏览器已能请求 `/auth/session`。管理端仍停在“恢复会话”：服务端对没有会话或失效会话返回 401，共享认证控制器清理状态并发出 logout，UserProvider 的订阅递增 identityEpoch，随后初始化完成回调因 epoch 过期退出，startupReady 一直未开启。

修复为 logout 订阅同时完成启动门禁，让匿名页面正常进入路由并显示登录入口；保留原有缓存清理与过期身份结果丢弃。没有放宽服务端认证或页面资源权限。

新增回归覆盖无会话与已有会话在启动时被清理两种场景；修复前重现 loading 卡死，修复后连同请求层测试共 13 项通过，Platform 1451 个严格类型文件通过。七维 hotfix review PASS；无新接口、凭据、依赖或视觉样式。

## 取消会话恢复过渡展示

按用户要求，管理端和工作台在正常会话初始化期间不渲染恢复登录提示或替代加载控件；认证完成后进入原有页面。保留初始化门禁，业务组件不会提前挂载；认证服务异常和移动宿主重连仍保留提示与重试入口。仅调整两个认证 Provider 的渲染分支，没有改变认证、缓存清理、跨标签同步或请求逻辑。

验证：管理端启动与认证请求测试 13 项、工作台对应测试 11 项通过，现有启动测试补充断言待初始化时无 status 和 loading 文案。两端全量严格类型检查（1451/2057 个文件）、变更文件 ESLint、arch-guard 和 diff 检查通过。工作台 DOM 测试因本机可选 canvas 原生模块未构建，使用仅作用于测试进程的预加载脚本让 jsdom 走其内置无 canvas 分支；未改动仓库依赖。七维 hotfix review PASS。

本次按用户指示仅提交 alpha1，不部署、不停止或重建 109 服务；线上尚未应用本节修改。
