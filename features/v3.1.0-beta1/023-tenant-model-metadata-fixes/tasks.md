# 实施任务

规格/设计：用户已确认完整计划并明确要求实施；spec/design 的确认由该计划及 IMPLEMENT 指令满足。仅 Platform，Client 不改；无迁移、worker 协议或历史授权写入。

- [x] T-01 角色展示。role 应用新增有界只读展示，user owner 提供确切用户绑定事实；department 在原授权分页后接入，Platform 标记失效绑定。覆盖 AC：AC-01、AC-02。验证：test_member_role_display、test_management_directory_scope、MemberRoleSummary。
- [x] T-02 模型范围。LLM 助手候选接入严格可见服务交集，状态探测前检查所选目标；Platform 共享行提示 Root，候选读取失败显式重试。覆盖 AC：AC-04、AC-05。验证：test_assistant_management_scope、test_model_status_verify、workflow ModelItem、ModelProviderRow、queryModelMigration。
- [x] T-03 文件元数据。提取 SPACE schema mutation owner，单弹窗恢复已有/新建字段和三类型编辑；幂等未知结果、草稿保留和挂载退役。覆盖 AC：AC-06、AC-07。验证：spaceFileMetadataDialog、spaceMetadataPanel、knowledgeSpaceFileDetail。
- [x] T-04 只读证据。核对已有工具修复和 116 部署差异，记录 3547 出站失败任务及源输入保护；恢复核查和部署清单。覆盖 AC：AC-03、AC-08。验证：test_visible_list_management_scope、test_source_move_input，以及 116-readonly-investigation.md。
- [x] T-05 验证交付。执行针对性回归、前端 lint/typecheck/i18n/build、后端增量 lint/架构守卫、七维审查；生成 opt-in 只读 E2E 和部署手工清单，整理本地提交。覆盖 AC：AC-01～AC-08。具体执行结果和未执行项见 validation.md。

## 实际偏差记录

- 起始远端从计划列出的 23997ee71f 前进到 33bcadaa3e；独立工作区基于后者，主工作区未修改。
- 依用户交付约定，116 只读且不部署。完整环境 E2E 本轮不运行；提供 5 个只读 opt-in API 用例及页面/写请求清单，状态明确 PARTIAL。未将本地组件/SQLite 回归当作环境验收。
- 原目录 enrich 单测改为隔离 role owner；真实有界读取和业务租户接线由新增 SQLite 集成用例覆盖。原模型缓存单测补齐当前目标及可见 provider 的显式测试组合，保留探测前失效的原断言。
- 宽范围旧测试存在租户上下文、失效 mock 和外部 MySQL 依赖；基线复核与具体结果记录在 validation.md。本次不改造无关功能或放宽生产校验来适配这些旧用例。

- 2026-11-18 合并适配：遵从目标发布线已确认的既有个人授权兼容规则；显示范围不再使历史绑定失效，新增 display/effective_roles 等价断言。更新结果见 merge-validation-20261118.md。
