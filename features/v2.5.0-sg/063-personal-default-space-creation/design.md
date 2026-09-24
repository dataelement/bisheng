# 默认个人库创建修复设计

Status: `confirmed`

新增 PersonalDefaultSpaceCreationGuard, 复用 KnowledgeMigrationLockRepositoryImpl 已有可配置 key、SET NX EX、令牌比较续期/释放实现, 不改变迁移全局锁。key 包含租户与用户 ID, 不包含可变用户名。

入口先只读查找, 缺失时进入 guard; 获锁后再次查找, 仍不存在才运行原有创建流程。等待最多 30 秒, Redis 调用最多 5 秒, 租约 60 秒, 每 10 秒续期。创建和续期分别运行任务, 丢锁立即取消并等待创建任务终止, 再释放自有令牌。外部取消也等待任务终止, 释放失败记录错误并依赖 TTL 回收, 不把释放错误替换为新的无锁创建。Redis 异常/超时返回独立业务错误 18005。

默认库读取增加 ID 升序, 与已有迁移脚本选择一致。创建中的异常保留日志和原有回查行为。新锁使用 Repository 层已有 Redis 实现, Service 不新增数据库查询或 DAO 入口。

落点: knowledge/domain/services/personal_default_space_creation_guard.py; knowledge_space_service.py; knowledge/domain/models/knowledge.py 的既有查询; common/errcode/knowledge_space.py; test/knowledge/test_personal_default_space_creation.py; test/test_personal_default_space.py 和 test/test_knowledge_space_service.py 中受影响的两个旧个人库测试仅补齐新增锁及原有标签依赖替身。

部署需所有调用入口实例更新后才能形成一致保护; 回滚仅回退代码, 不涉及数据变更。线上 Redis、真实 MySQL/DM8 和跨进程发布验证单列限制。库记录已提交但归属未写入的故障遗留不在本次修复范围。
