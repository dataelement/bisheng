# 2026-10-23 开发整合 L2 证据

本目录是开发合入审查，不是全 Feature 验收通过证明。三条审查线均未新增全量测试或远端操作，原报告先记录发现，再追加限定复审关闭，避免抹掉审查过程。

- [backend 七维](./backend.md)：D1 设计当前快照漂移已定向关闭；代码未发现阻断。
- [runtime 七维](./runtime.md)：控制器/生命周期/SQLite/资源围栏核对及 D1 已关闭。
- [交付/发行/CLI/SDK](./delivery.md)：CI 同版本跨入口并发项已修并定向复审关闭；仓库外写入边界保留。
- [定向验证](./validation.json)：本轮 1+17 项与静态整合结果。
- [F086 文档恢复来源](./f086-recovery-manifest.json)：从原 dirty WT 收回 78 文件的原始字节摘要；部分设计/审查/状态文档随后在本整合树更新，因此此清单不是当前文件哈希门禁。

F086 implementation-files.sha256.json、旧 validation/local suite、2026-10-21 CI 等均是当时源码的历史快照，不用最终整合内容覆盖或重贴通过标签。当前完整边界见上级 code-review.md 与 docs/reviews/vibe-development-integration-2026-10-23.md。
