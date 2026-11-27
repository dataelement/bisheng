# alpha1 HTTP 会话协调兼容修复

2026-11-27，基线 `7f665b1704`。部署验收发现，通过 HTTP 访问非 localhost 地址时没有 Web Locks 和 `crypto.randomUUID()`，会话协调的 IndexedDB 分支在发出认证请求前失败，页面显示认证暂不可用。

复用项目已用于对话、附件和移动操作的 `uuid` 包 `v4`，替换两处原生 `crypto.randomUUID()`：租约 owner 和无 BroadcastChannel 时的通知 nonce。检查过现用版本的浏览器实现：没有原生 randomUUID 时使用 `crypto.getRandomValues()`。没有新增随机数生成器、Math.random 降级或绕过跨标签会话锁。

将 uuid 版本纳入工作区 catalog；客户端和共享 API 包共同引用，锁定版本仍为已有的 11.1.1。

验证：共享包 85 项测试通过，包含没有原生 randomUUID 时的 IndexedDB 互斥；共享包 lint/typecheck、Client/Platform 全量严格类型检查、隔离目录 frozen lockfile 校验及 diff 检查通过。发布后的 HTTP 页面验收另记部署记录。

Hotfix review：边界、权限、并发、信息泄漏、测试、风格、文档七个维度均 PASS。会话 ID、凭据、租约续期和 fencing 协议没有改变。
