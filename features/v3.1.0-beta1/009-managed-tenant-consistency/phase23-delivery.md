# 租户上下文第二、三阶段本地交付

2026-11-14。**本地开发完成，匹配部署及现场验收未执行。** 用户确认组织页跟随所选租户、只管理挂载子树。BiSheng分支codex/3.1.0-beta1/tenant-context-phase1延续第一阶段740900516d；网关独立分支codex/tenant-context-unification，基线62399806，本地配对提交aa4f272b6e9fe6e073415034cb0ece5b1c3e34e3。原两个主检出保留，未合并、推送或部署。

## 已交付

- 实际端点唯一范围声明、选路后统一准入、严格自举和切换未知处理；两套前端、原生事件流及WebSocket接线。资源目标证明独立于超管动作快捷判断，平台身份/本人政策/独立凭据分开。
- 组织与人员限于业务挂载子树，物理Root行不迁移；Root视图排除子租户。子租户旧创建用户表单初始化挂载根，本人昵称/资料及网关本人主部门使用真实身份。兼属成员可见，外国主属普通角色及账号控制不开放。
- 创建人及授权人员已知编号姓名保持可显示；部门授权名称、摘要和权限解释按业务归属处理，止于挂载边界。旧变量父资源/版本校验、角色失败旧路径回退及技能负向归属端口补齐。
- 网关仍执行敏感词/限流，通过后端核对目标及对象；旧组资源退役，手工组织同步明确平台操作，旧拦截日志明确仅平台超管汇总。已知无权与范围未知分开响应。
- 工作流、复制及导出关键任务复核持久目标，拒绝冲突，关键任务执行体再次检查；沿用现有Celery消息格式，不追随最新管理选择。
- 分页只读预检、自动生成资料检查和持续集成门禁；零新增业务表、字段或迁移，不修历史数据、用量、绑定、引用或队列。

详细技术合同见[增量设计](phase23-design.md)，影响与测试重点见[测试交接](../../../docs/reviews/tenant-context-phase23-impact-test-focus-20261114.md)。这里二、三阶段指租户上下文方案，不包含角色方案的历史逐行修正和行政划分承接。

## 验证

| 检查 | 本次结果 | 证据 |
| --- | --- | --- |
| 后端定向回归 | 230通过 | /private/tmp/tenant-phase23-backend-final.log；包含真实SQLite关系、组织HTTP、角色、姓名、消息目标和负向校验 |
| Platform定向回归 | 37通过 | /private/tmp/tenant-phase23-platform-final.log |
| Client定向回归 | 23通过 | /private/tmp/tenant-phase23-client-final.log |
| 共享请求包 | 22通过，tsc通过 | /private/tmp/tenant-phase23-shared-final.log、tenant-phase23-api-client-types.log |
| 网关Java 17编译及测试 | 25通过 | 网关target/surefire-reports；离线Maven容器，未启动服务 |
| 两前端仓库标准lint/typecheck | 全部通过 | pnpm lint、pnpm typecheck；退出码见phase23-validation.json |
| 原始全量tsc | 有存量错误，无新增源位置/错误代码 | Platform627对627，Client474对474；两条未改翻译表达式仅联合类型打印排序不同。仓库标准tsc-strict按既有冻结规则通过，不把原始tsc写成通过 |
| Python Ruff | 无新增诊断 | 四个旧文件共159条存量，基线173条；新文件通过，未扩散修复存量样式 |
| 架构/差异检查 | 无VIOLATION；diff --check通过 | 两处旧API模型导入为RULE-3迁移期WARNING |
| 登记/生成资料 | Python 963、网关80个方法/路径组合一致 | export_request_scopes.py --check --gateway-root …；数量不等于全部功能已现场验收 |
| 专用环境端到端 | 12跳过，PARTIAL | 无专用测试身份/数据；未拿116既有业务数据替代 |

机器摘要见[phase23-validation.json](phase23-validation.json)。Platform退役API删除后，ESLint自动prune仅将pro.ts旧any抑制计数13减到10。Client测试使用临时预加载使不可构建的可选canvas按“未安装”降级，未安装或修改共享依赖；异步请求测试显式等待准备完成。直接调用Celery.run的旧测试补显式上下文，不能用MagicMock伪造租户头。

## 历史兼容及上线要求

资源、创建人、角色、菜单、普通绑定、用量和授权稳定编号保持。坏版本/文件/授权父子或未知引用可能在新门禁下被明确拒绝，列表减少不是删除；不按创建人主属反推资源归属。Root无部门历史账号保留。只读预检输出截断、续页、跨范围需领域证明及UNKNOWN，不宣称历史已全兼容。

2026-11-16修订：需匹配发布两前端、Python、Worker并更新静态缓存；Java可不部署或保留旧版。旧聊天回写兼容见[本轮修订](optional-gateway-compat.md)，此前Java增强保留独立待合并，不作为前提。旧页面对租户GET也可能缺头，必须更新；两个聊天回写按身份及持久会话归属处理；旧消息只在有持久证明时恢复，未知消息需单独盘点。资格/归属核验增加数据库或后端请求，目标环境需测延迟和超时。

**尚未完成的验证**：MySQL/DM8、实际浏览器、真实Celery进程、网关与后端联合部署、外部OpenFGA/存储、真实历史只读盘点及远端持续集成。完整测试范围与步骤见[e2e-checklist.md](e2e-checklist.md)及八列[test-cases.md](test-cases.md)。回退需对应版本组合，不能以清选择缓存冒充业务回滚。


## 2026-11-16 集成进展

用户已授权合入/推送；已在最新远端发布线的隔离工作树完成集成与关联回归，Gateway按用户确认仅推修复分支。前文2026-11-14状态为历史快照，最新来源、冲突处理与验证见[integration-20261116.md](integration-20261116.md)。
