# 版本变更接口资源鉴权修复

日期：2026-11-18。实现基线：`23b9fb26551a05dca3427bea15678a0c62626ded`，
独立分支 `codex/knowledge-version-resource-auth-20261118`，目标 `feat/3.1.0-beta1`。
按用户要求修复上一轮静态审查发现的鉴权遗漏，复用已有权限动作和接口协议，走 hotfix 审查。

## 根因与修复范围

以下入口原先进入 `KnowledgeVersionMutationApplication._execute` 后只验证身份/租户、
功能开关、业务状态及锁定版本链，没有调用资源动作鉴权：

- `POST /api/v1/knowledge/space/document/link`
- `POST /api/v1/knowledge/space/version/merge`
- `POST /api/v1/knowledge/space/version/{version_id}/set-primary`

前台/后台按钮隐藏不能保护直接 HTTP 请求。现在三个入口共同要求实际所属空间的
**`knowledge_space.edit`**，通过 `permission.application.business_authorization.require_business_action`
执行；普通用户持有该动作即可操作，不增加管理员角色门槛，也不自行实现超管放行。
不新增 `knowledge_file.edit`，不改变既有角色或授权数据。

## 数据流与并发边界

1. 保留功能开关在 SQL 之前的检查，并冻结原 UserPayload、actor、凭据及管理租户范围。
2. 用新鲜原生只读会话解析实际归属：关联/合并读取请求文件；设主版本读取版本及其所属文档。
   读取复用现有严格租户查询，验证根资源确为当前租户的 SPACE；请求附带的空间提示不参与授权。
3. 只读事务显式回滚并关闭，再调用 F048 检查该空间的 `edit`。权限 I/O 不持有版本链写锁，
   查权失败或权限服务异常直接传播，不打开写事务，不发送成功业务审计。
4. 新鲜写会话按原顺序锁定及校验完整版本链。实际空间 ID 和租户必须仍与准入时相同，
   否则返回计划冲突；鉴权期间改了租户/身份也拒绝。不会把旧空间的权限用于新空间。
5. 原版本链修改仍只有一个 SQL 提交；保留同空间限制、解析状态、重复内容、重建互斥、
   单主版本约束及未知提交结果的原始异常，不重试、不推断补偿。

权限拒绝沿用现有错误封装：业务码 403；没有变更全局 HTTP 状态或响应结构。
历史版本删除仍走既有统一删除应用；版本列表/历史读取没有叠加编辑权限。
无数据库迁移、前端改动、依赖变更、现场数据修改或 116 部署。

## 验证与证据

- 新增 **27 项** HTTP 路由 → 实际 DI/Service → 实际 Application/Repository → SQLite 集成用例。
  权限保留实际 `require_business_action`，仅替换其下层 `check_business_action`，没有 mock 掉版本写入或回滚。
- 覆盖三个入口的只读拒绝、普通编辑用户成功、权限服务异常、跨租户 ID（普通用户和超管）、
  超管管理子租户时保留 Root 身份、鉴权期间整条文档链跨空间移动、租户切换，
  以及只持有 A 空间权限不能改 B 空间。拒绝时校验所有版本/文档/文件数据及成功审计不变。
- 修改前代码对照：三个只读、三个权限服务异常场景 **6 failed**，均在全量数据快照断言处证明仍有写入；
  修复后这些用例通过。对照只在独立 SQLite 数据库执行，没有真实越权写现场。
- 关键写入、事务异常、实际 HTTP 接线、旧关联/设主版本及重建互斥：**146 passed**。
  保留原先“只提交一次”的断言；读取新增一个回滚会话，写入仍一个会话/一次提交。
- 集成最新远端 `c6db361d17` 后，扩大到知识空间/文件权限适配器、资源解析一致性、
  目录禁用动作及旧版本相关测试：**210 passed / 8 failed**，27 项安全用例全部通过。
  8 个失败在修改前的两个生产文件下逐项复现：
  5 项历史删除 fixture 缺 `knowledge_processing_fence`，3 项旧测试仍预期 HTTPException 而实际是
  `VersionManagementDisabledError`。这些业务不在本次修复范围内，没有为过测试修改其语义。
- 修正公用 SQLite Knowledge fixture 的两个已有 ORM 字段 `copy_source_id` / `copy_target_id`，
  否则关联/设主版本旧测试在 seed 阶段就因查不到列失败。这只是测试建表，不是产品 DDL。
- 所有变更 Python 文件 Ruff format/check、架构守卫及 `git diff --check` 通过。
- MySQL/DM8/OpenFGA 实际部署环境未执行联合 E2E；本地 HTTP 集成不宣称真实鉴权存储验收。
  部署后应使用实际只读、编辑及超管子租户账号复核业务码与版本链/审计结果。

## sdd-code-review

| 维度 | 新增 High / Medium | 结论 |
|---|---|---|
| 边界条件 | 0 / 0 | PASS：缺失/错租户资源、文件类型、开关和原业务错误 |
| 权限与认证 | 0 / 0 | PASS：唯一 F048 入口，按实际空间准入，普通用户和超管范围覆盖 |
| 并发安全 | 0 / 0 | PASS：鉴权不持写锁，锁内再验归属，原一提交/未知 ACK 语义保留 |
| 信息泄漏 | 0 / 0 | PASS：无新凭据或数据日志，外租户对象在查权前不可用 |
| 测试覆盖 | 0 / 0 | PASS：直接 HTTP、实际 SQL/事务、红绿对照，已披露 8 项基线失败 |
| 代码风格 | 0 / 0 | PASS：分层、双库查询、格式和架构守卫 |
| 文档同步 | 0 / 0 | PASS：F118 当前设计新增动作映射，上一轮界面审查链接到本修复 |

**Overall: PASS（本次接口鉴权修复范围）**。既有 8 项基线失败与真实环境 E2E 限制如上。
