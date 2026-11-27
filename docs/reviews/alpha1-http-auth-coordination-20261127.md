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
