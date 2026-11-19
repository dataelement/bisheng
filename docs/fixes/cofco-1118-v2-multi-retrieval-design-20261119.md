# cofco-1118 v2 多库检索排序修复设计

目标分支：`feat/cofco-1118-3.0.0-beta1`，基线 `c48b535e2c`。本修复按该分支源码独立实现，未 cherry-pick 或合并 beta1 提交。

## 1. 问题与范围

本分支 `POST /api/v2/filelib/retrieve` 直接调用 `KnowledgeSpaceChatService.aretrieve_chunks`，各库分别 RRF 后按库顺序拼接再取 `top_k`。结果受库入参顺序支配，前库可占满全部名额。

按用户要求修正为已有工作流采用的多库排名：两路分别跨库按原始分数排序，再统一 RRF，最后取 K。请求/响应字段、单库路径、权限协议与中粮审批规则不变。本次是范围已明确的 bugfix，不新增检索门面、数据库模型、配置项或评分算法。

## 2. 与 beta1 的关键差异

| 位置 | beta1 | cofco-1118 的处理 |
|---|---|---|
| v2 入口 | 统一门面与 `RetrievalEngine` | 原端点 → 聊天服务；修复落在服务的 `aretrieve_chunks`，不引入 F052/F118 架构 |
| 权限/类型 | 门面预判与统一不可及错误 | 保留空间 gate、文档库 `use`、NotFound 和 10962；不支持 QA/个人库 |
| 审批期视图 | 不含此分支的 F046 查询/名称投影 | 各库保留 `project_mutation_retrieval_query`、`project_mutation_retrieval_names`，未发布/删除硬拦截继续通过原 visibility service 生效 |
| provider 构造 | 转发 F118 `login_user` 参数 | 沿用本分支原工厂调用签名与操作人，不把兼容参数传给底层 VectorStore |
| 权限故障 | 门面权限异常直接映射 | 不修改旧端点的 `OpenApiAuthDependencyUnavailableError`（503/26030）映射 |
| Eplus 机器人 | 独立产品路径 | 中粮机器人有自身词法/局部排名融合，本次不将其引入通用 v2，也不修改机器人排序 |

## 3. 方案与选择理由

在现有聊天服务内增加私有多库入口 `_aretrieve_chunks_multi`；单个唯一库仍调原 `_aretrieve_chunks_dispatch`。重复库 ID 去重，避免同一候选被重复召回后隐式加权。

逐库串行进行资源存在性/类型/权限校验、标签解析和 `build_index_prefilter`，然后构建本分支原 Milvus/ES stores。每库一个请求内候选任务保留两路 `(Document, score)`，在空结果时按原两轮倍率扩量。任务间搜索可并发；F046 查询扩展、名称投影与结果层过滤受同一请求内锁保护，避免并发使用版本仓储的 `AsyncSession`。

查询投影分别作用于该库两路搜索；名称/正文投影在文档副本上执行并保持分数配对。投影后用原 `post_filter_retrievable_files` 过滤，再供两个 `_OpenApiRecallChannel` 适配器读取同一任务结果。适配器只在当前请求存活，不形成跨请求权限缓存。

两个现有 `MultiRetriever` 分别对向量/关键词候选全局排序，随后 `KnowledgeRetrieverTool._rrf_rerank` 做一次 RRF/文本去重。中间不额外设置 `finally_k`，避免每库长度过滤前丢失其它库的可用候选；各库原始召回仍受两轮 K 倍率约束。按融合排名独立累计每库 `max_content`，最后截取 `top_k` 并调用原更新时间补齐方法。

选择这一方案是为了直接复用分支已有排序工具，保留本分支业务过滤和单库链；逐库局部 RRF 分数不能替代原始召回分数再做全局比较。发生任何候选/权限错误时取消并等待同级任务，然后原样上抛给现有端点处理。

何时重新考虑：跨 embedding 模型/ES 索引的分数校准应统一演进已有多库工具，或引入公共 rerank；未来主动迁移统一门面时再单独处理本分支 F046 投影和错误协议。

## 4. 数据流与契约

`v2 原身份解析与 version_repo` → `aretrieve_chunks` 参数校验 → 单库原分派 / 多库逐库准备 → 每库两路原始分数召回 + F046 投影 + 原结果过滤 → 两路 `MultiRetriever` 全局排名 → 一次 RRF → 每库限长 → 前 K → 更新时间 → 原 DTO。

`top_k` 继续由本分支 schema 限制在 1–200，`max_content` 保留本分支原校验范围，不引入 beta1 的 60000 上限。长度截止沿用原工具的整块方式：累计值超过上限后不纳入该库后续块，跨过上限的整块保留。

## 5. 已知坑与验证

- F046 名称投影会原地改写正文与 metadata。必须投影副本并保留原始 score 配对，不能直接改写 store 返回的共享候选。
- 两路共享每库候选任务，避免 Milvus/ES 聚合时各触发一遍同一库召回；失败必须收束同级任务，不能留到请求 session 关闭之后。
- 旧 F029 测试用裸 `MagicMock` 替代 visibility，缺少中粮异步投影 stub，基线已有 5 项失败。按 `cofco-merge-playbook.md` §2.2 补齐直通 `AsyncMock`，不放宽生产守卫。
- `test_cofco_v2_multi_retrieval.py` 使用真实 `MultiRetriever` / RRF，覆盖库顺序、工作流结果等价、原 F046 名称投影、两个资源类型、每库预算、标签、重试、权限身份、503 映射与异常收束。
- 未执行真实 Milvus/ES/OpenFGA 联调或部署；中间件传输由测试替身隔离，部分主版本与 F046 资格规则使用分支既有测试验证。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-19 | 基于 cofco-1118 独立修复多库排序，保留中粮过滤/审批投影/身份和错误映射 | 用户明确要求核对分支差异，不直接摘 beta1 提交 |
