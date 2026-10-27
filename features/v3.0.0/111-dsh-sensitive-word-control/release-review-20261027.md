# DSH 增量发布代码审查（2026-10-27）

范围：统一请求编号、移除未关联检查/请求明细独立视图及相关跳转、命中配置词快照与授权详情展示（T212–T243，AC-62、AC-63、AC-64、AC-65、AC-66）。本轮不是原F111全部特性的最终审查，原15项待验任务及DM8实测继续保留。用户已明确授权合入最新feat/bisheng-work-120-main、推送、CI构建及仅109 DSH13001部署，覆盖此前这些改动“不提交/推送/部署”的限制；历史验证章节仍按发生时保留。

B源c11c12b18与最新目标dfadd7ab3正常merge，自动合并三语bs.json，无冲突；其他最新目标分支修改均保留。G源2ed8c5b7基于最新c999f9bf，无分歧。未修改其他工作树或其未提交内容。

按仓库/sdd-code-review七维逐项读取实际业务文件、迁移及配对测试：

| 维度 | 结论 | 核验 |
|---|---|---|
| 边界条件 | PASS | 单个规范非零UUID，缺失/非法/多值回退；词快照可选/严格双方向、合计20词、256码点、非空白/无重复/有效Unicode；旧缺失/null兼容 |
| 权限与认证 | PASS | 沿用原请求详情授权与租户过滤；backend不感知Gateway配置；词值不进入匿名阻断消息或主列表新查询 |
| 并发安全 | PASS | Gateway转发前赋ID；旧backend显式有效ID兼容；冻结CompiledPolicy；Observation深拷贝；原幂等事件/事务/投影不变 |
| 信息泄漏 | PASS | 仅保存有限配置词，无正文上下文或凭据；toString不输出词；React按文本渲染；普通日志不增加词值 |
| 测试覆盖 | PASS_WITH_NOTES | 合并后B190PASS，G905PASS/10原真实DB SKIP，Platform269PASS。既有全feature/DM8/容量不冒充通过，部署API/页面验收另记 |
| 代码风格/架构 | PASS | 复用既有HTTP/DTO/JsonType/前端组件，无新依赖；新迁移唯一head、DDL-only、可空且幂等，拒绝破坏性回退；Ruff和架构检查保留前轮通过证据 |
| 文档同步 | PASS | spec/design/tasks及双仓验证记录已同步，部署顺序和历史无法还原说明明确 |

合并后frontend完整lint、workspace typecheck、i18n和locales检查均PASS；最新目标分支已修复旧95项lint基线问题，历史记录不改写。Platform生产构建已执行；实际日志/private/tmp/dsh-id-audit-release-20261027/，CI镜像仍须另核Git SHA及digest。

结论：本次增量允许发布；不以此勾选原T119–T132、T180。backend必须完成f111_matched_words迁移及全部实例升级后再升级Gateway，回退先Gateway且保留新增列。最新目标同时包含工具/技能权限f048-v6升级，按其upgrade.md在DSH隔离Store执行只读dry-run、确认Store/checksum及备份后完成必要维护，不影响其他环境。发布/现场结果单独记录。
