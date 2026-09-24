# Feature: F107 共享知识空间直接解析入库

**关联规格**: [requirements.md](./requirements.md)、[design.md](./design.md)  
**优先级**: P0  
**所属版本**: v2.6.0  
**状态**: ✅ 用户已确认实施

## 概述

共享路由生效后的 SPACE 上传解析和重解析直接写租户共享 collection/index，不再把旧的每空间
collection/index 作为运行时 staging。collection/index 继续按租户物理隔离；为兼容现有共享
collection 的非空字段，writer 在 chunk metadata 固定补写 `tenant_id=1`，查询不使用该字段。

## 验收摘要

- shared route：parse/transform → shared writer；禁止 legacy fallback。
- legacy route：行为保持不变。
- direct write 使用 canonical identity/generation 并可幂等重试。
- metadata 固定写 `tenant_id=1`，query 无 tenant filter，物理名称仍为 `{prefix}_{tenant_id}`。
- 正常 projection 只收敛 membership，legacy loader 仅用于迁移/修复。

## 边界

- 不删除 SQL `tenant_id`。
- 不自动执行生产外部存储迁移。
- 不删除旧数据。
