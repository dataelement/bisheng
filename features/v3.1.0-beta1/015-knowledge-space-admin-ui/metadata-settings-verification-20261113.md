# 元数据与空间设置验证 / 七维复核

日期：2026-11-13。目标：AC-27–AC-29。基线：`feat/3.1.0-beta1` / `33d7a68b8274b944bd115f1c6a438b9def9e4753`。按用户新要求直接在目标分支开发，用户随后授权提交推送；下述检查对应本次代码树，Git 交付另行核对远端 SHA，不表示部署或真实索引验收。

## 实施与验证

复用旧元数据列表、六个只读内置字段、新建/重命名弹窗和删除确认，内部调用现有原生预检及确认。菜单收敛为删除空间/权限管理，引用来源继续只在原删除流程中按需披露。设置补齐现有前台选项，保留 feature gate、动作权限、部门空间限制、私密切换提示及保存失败后的输入。

| 验证 | 结果 | 证据与范围 |
| --- | --- | --- |
| 定向回归 | 12 文件 / 148 项通过 | spaceMetadataPanel、spaceSettingsEditor、spaceSettingsForm、f118KnowledgePage、knowledgeSpaceManagementView、f118SpaceProcessingEntry、f118KnowledgeLibraryDialog、knowledgeSpaceContract、f118SpaceDetail、useKnowledgeDeletion、KnowledgeDeletionDialog、knowledgeDeletion API。 |
| 全前端质量门 | 通过 | 在 `src/frontend` 执行 pnpm lint/typecheck/check-i18n；最终 platform lint:prune 也通过，旧压制项只减少 3 项。 |
| 架构/大小/空白 | 通过 | 本轮 16 个 TS/TSX 文件运行 arch-guard，均不超过 600 行；git diff --check 通过。设置 API 独立封装，未增大原大 API 文件。 |
| QA 模板 | 通过 | test-cases.md 中 TC-MS-001–012 均为规定的八列。 |
| 本地浏览器 | 通过 | 实际组件与真实 UI 库、CSS、i18n；仅使用临时本地 API fixture，无真实服务写入。元数据新建、重命名、删除，内置字段及设置保存已操作；1024px 页面无横向溢出；控制台无 error，仅两条既有 Router future warning。 |
| 原生服务 E2E | 未执行真实环境，离线 1 skip | `F118_E2E=0 PYTHONPATH=. .venv/bin/python -m pytest --confcutdir=test/e2e test/e2e/test_e2e_f118_unification.py -k test_ac45_four_native_kinds_finish_real_worker_and_index_work -q`。10 项 deselected；未配置和启用专用部署。 |

浏览器核验发现并修复了旧本地插入与 schema 响应刷新叠加导致的新建重复行，并新增断言只出现一行。确认 ACK 丢失用例验证重试只有一次预检，且两次确认使用完全相同的 confirmation_id、plan_digest、idempotency_key。内置名、预检不完整和退场后响应均不创建任务。

浏览器保存实际观察到 payload：`auth_type=approval`、`is_released=true`、`auto_tag_enabled=true`、`auto_tag_library_id=null`，自定义标签为采购/财务/合同，名称为本次修改值。临时入口、Vite 配置和页面均已删除，服务已停止。

没有修改 backend/client 源码或数据库契约。服务端预检的实际路径经源码核对：LegacyMetadataWriter 同样调用原生 aprecheck/acreate，MetadataProcessingOwner 与 MetadataProcessingService 校验字段及配置版本、文件版本/source 范围和索引 generation。恢复旧交互不等于移除这些检查。

## 七维审查

审查范围：基线以上本轮 platform 和 feature 文档差异，排除用户原有 docs 修改；按 sdd-code-review 框架由主 agent 自查，未声明为独立 agent 审查。

| 维度 | HIGH | MEDIUM | 结论 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | PASS：空 schema、缺失访问/发布字段、非法名称、标签重复/超量、不完整计划和失败输入保留有覆盖。 |
| 权限与认证 | 0 | 0 | PASS：详情配置保留 edit，分享另需 manage_permission，菜单按有效动作，后台 API 做最终鉴权；标签可见性及部门限制保留。 |
| 并发安全 | 0 | 0 | PASS：完整 scope/空间/挂载隔离，退场检查、提交锁、版本预检、未知 ACK 幂等键重用；字段刷新不叠加乐观插入。 |
| 信息泄漏 | 0 | 0 | PASS：不增加引用入口，原服务端 disclosure 仍决定可见来源；无密钥、真实用户数据或新增后端地址。 |
| 测试覆盖 | 0 | 0 | PASS：148 项本地回归与浏览器操作对应三个 AC，真实环境/Worker 验收明确未完成。 |
| 代码风格 | 0 | 0 | PASS：复用旧业务 UI 和共享组件，未增加依赖/新压制项，死表单删除，质量门和行数检查通过。 |
| 文档同步 | 0 | 0 | PASS：spec/design/tasks、八列 QA 与本验证同步；默认旧接口的基本信息白名单保持不变。 |

总体：PASS。本地交付无新增阻断项。仍需在同版专用环境核验元数据的真实异步索引结果、真实标签库/TXT 及非管理员动作授权；本地通过和 E2E skip 均不构成上线验收。
