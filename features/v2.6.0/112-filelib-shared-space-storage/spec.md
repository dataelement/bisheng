# Feature: F112 Filelib 文件接口统一 SPACE 共享存储

**关联需求 / PRD**：[requirements.md](./requirements.md)，依据 2026-10-22 用户请求及范围选择。

**优先级**：P0

**所属版本**：v2.6.0

**Status**：IMPLEMENTED_LOCAL

**当前门禁**：Discovery 与规格均已获用户确认；已按 tasks.md 实施，验证见 verification.md。

## 1. 目标与范围

作为 Filelib 调用方，我希望文件创建、入库、列表、详情、检索及删除均使用现行 SPACE
共享文档模型，不再因为调用旧 ES/Milvus 适配器失败。

本次包含下表 14 个接口。6 个 QA 接口和统计下载保持原状，不将其他业务类型批量改成 SPACE。

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|---|---|---|---|
| AC-01 | Filelib 调用方 | 缺省类型创建/列举资源 | 默认 SPACE；创建共享目标绑定及正常空间归属，无独立索引 |
| AC-02 | Filelib 调用方 | 传入非 SPACE、别名冲突或混合检索 | 副作用前拒绝，不修改原资源类型、不调用旧存储 |
| AC-03 | 已授权用户 | 查询正文，文本对象存在/不存在 | 返回完整有序正文；未命中文本对象时走共享分块 |
| AC-04 | 已授权用户 | 查询发布/分享入口、切换版本后的内容 | 解析实际内容身份及正确摘要，不读旧代次；历史非主版本拒绝正文读取 |
| AC-05 | 有上传权限的用户 | 使用三种写入接口并重试 | 共享写入身份和归属正确，失败状态真实，重试不重复有效内容 |
| AC-06 | 有删除权限的用户 | 单文件/同空间批量删除 | 遵守已有分发语义，保留有效引用内容；跨空间批次副作用前拒绝 |
| AC-07 | 有对应权限的用户 | 清空/删除 SPACE | 清空保留空间，删库走退役；不 drop 共享目标，不误删有效引用的原对象 |
| AC-08 | 已授权用户 | 检索或获取原文件地址 | 只返回授权范围内结果，签名指向实际原对象，无权文件不签名 |
| AC-09 | Filelib 调用方 | 触发路由/后端/投影/内容缺失/版本变化错误 | 明确失败，不回退旧库，不伪装空正文成功 |
| AC-10 | 不同权限用户 | 无权/跨租户访问、冻结时操作及 external_id 查询 | 保留身份策略，执行领域权限；冻结禁止写入且保留合法读取 |
| AC-11 | 既有调用方 | 调用文件业务接口 | URL、既有成功字段和分页结构保持，正文与切片数量语义明确 |
| AC-12 | QA/统计调用方 | 调用排除的 7 个接口 | 路由、请求/响应、依赖调用和行为不变 |

详细边界与验证映射见 [requirements.md](./requirements.md)；两个文档使用相同 AC 标识。

## 3. 全量端点契约

下列路径均以 `/api/v2/filelib` 为前缀；除标明的变化外，URL、HTTP 方法和既有成功返回结构保持。

| Method | Path | 目标行为 | 主体 / 约束 | 验收 |
|---|---|---|---|---|
| POST | `/` | 默认创建 SPACE，绑定共享目标；补齐正常空间归属 | 沿用 default_operator；复用空间创建资格 | AC-01, AC-02, AC-10 |
| PUT | `/` | 仅修改 SPACE 的名称、描述 | 沿用 default_operator；复用空间编辑权限 | AC-02, AC-10 |
| GET | `/` | 默认 SPACE，沿用空间列表 cursor | 沿用 Token + 可选 external_id | AC-01, AC-02, AC-11 |
| DELETE | `/{knowledge_id}` | 通过现有空间退役/分发规则删除 SPACE | 沿用 default_operator；禁止 force 绕过 | AC-07, AC-10 |
| DELETE | `/clear/{knowledge_id}` | 清空空间内容，保留空间及作用域 | 沿用 default_operator；沿用领域删除策略 | AC-06, AC-07, AC-10 |
| POST | `/file/{knowledge_id}` | 现有异步解析入库走共享直写 | 沿用 default_operator、配额、回调 | AC-05, AC-10 |
| DELETE | `/file/{file_id}` | 按入口及分发语义删除 | 沿用 default_operator；逐文件校验 | AC-06, AC-10 |
| POST | `/delete_file` | 同空间批量删除，预校验后执行 | 沿用 default_operator；跨空间批量拒绝 | AC-06, AC-10 |
| GET | `/file/list` | 保留既有文件列表；摘要使用共享内容身份 | 沿用 Token + 可选 external_id；不改变分页协议 | AC-04, AC-10, AC-11 |
| GET | `/file/detail` | 文本对象或共享分块返回正文 | 沿用 Token + 可选 external_id；校验入口可读性 | AC-03, AC-04, AC-09, AC-10 |
| GET | `/file/source_url` | 解析实际内容文件后签发原文件地址 | 沿用现有 Token/业务用户与 view_file 规则 | AC-08, AC-10 |
| POST | `/chunks` | 同步解析接口接共享直写 | 沿用 default_operator、配额和响应 | AC-05, AC-10 |
| POST | `/chunks_string` | 提供的文档切片接共享直写 | 沿用 default_operator；复制元数据，避免原地修改输入 | AC-05, AC-10 |
| POST | `/retrieve` | 只允许 SPACE 检索，不进入非 SPACE 检索器 | 沿用 Token + 可选 external_id | AC-02, AC-08, AC-10 |

明确不改：`POST /add_qa`、`POST /add_relative_qa`、`DELETE /qa/{qa_id}`、
`POST /update_qa`、`GET /detail_qa`、`POST /query_qa`、`GET /download_statistic`。

## 4. 参数和响应

### 资源类型

- 创建请求 `type` 和资源列表查询缺省为 `3`，显式值仅接受 `3`。
- 列表继续接受 `knowledge_type` 别名；同时提供的两个值必须一致。
- 所有文件接口按服务端查出的资源类型校验，不信任调用方传入的类型。
- `/retrieve` 中任一 ID 不存在或不可访问时沿用领域拒绝，任一有效资源非 SPACE 时拒绝整单。
- 不修改全局 `KnowledgeCreate` 的默认值，以免影响本次范围外的其他入口。

### 创建

- 保留名称、描述等现有字段；Filelib 专用创建 DTO 可接受 `space_level`、`department_id`、`is_clinic`。
- `space_level` 默认 `team`，由当前操作人拥有；显式公共/部门/科室库按现有服务校验归属和资格。
- 不允许以兼容旧请求为由新增个人库、伪造 scope 或绕过配额与权限。
- 模型和物理索引/collection 由共享路由决定。历史 `model`、`index_name`、`collection_name` 字段可以省略；
  显式提供时须与租户目标一致，否则返回参数错误，不能创建第二套目标。

```json
{
  "name": "政研资料",
  "type": 3,
  "space_level": "team",
  "description": "政研 Agent 使用的共享文档"
}
```

### 文件与内容

- 文件列表保留 `{data, total, writeable}` 和 `page_num/page_size`；不增加新的 ReBAC 列表扫描或改变分页。
- 资源列表保留既有 cursor 协议。若实现必须引入新的权限过滤分页，须先更新版本契约和本规格，不暗中切换。
- 详情保留 `file`、`content`、`chunk_count`。元数据标识访问入口，正文解析到实际内容文件。
- 文本对象命中时 `chunk_count` 保持既有语义：非空为 1、空为 0；共享分块路径为实际返回切片数量。
- 未处理成功文件保留既有空详情；成功文件若共享投影未就绪，不能伪装成正文为空且成功。
- 文本对象命中也必须先完成入口、版本和就绪校验，不能绕过共享生命周期。
- 详情维持完整正文返回，不能误用 MCP 单页默认长度截断；读取期间版本变化时拒绝混合版本结果。
- 共享正文仅支持当前有效主版本；历史非主版本文件不能配上当前主版本正文，返回 18098 状态冲突。
- 详情暂沿用 400/404/409/422 的既有参数、未找到、编码重复与类型校验约定。

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file": {
      "id": 345,
      "knowledge_id": 118,
      "file_encoding": "SGGF-RPT-QM-20260400000007",
      "file_name": "report.pdf",
      "file_size": 256,
      "status": 2,
      "update_time": "2026-10-22 10:00:00",
      "is_primary": true,
      "document_type": "RPT",
      "categoryID": "入库分类测试",
      "categoryGroupClassCode": "分类编码测试",
      "docTypeCode": "分类赋码测试"
    },
    "content": "完整解析正文",
    "chunk_count": 1
  }
}
```

### 删除与清空

- 文件删除、清空和删库复用现有空间生命周期能力，管理入口/发布/分享入口遵守既有规则。
- 管理入口删除可能按既有分发规则级联或被拒绝，本次不能自行扩大其范围。
- 同一文档仍有有效引用时，必须保留其共享内容和原对象；不得按空间 drop 共享索引/collection。
- `/delete_file` 保留文件 ID 数组请求；跨空间批次使用已有业务错误明确拒绝，在首个写操作前完成校验。
- 清空保留空间、scope 和授权；不调用“删库后重建”模拟清空，不在请求内迁移其他空间。
- 大范围生命周期操作沿用现有事务/持久任务能力；不能在部分成功时返回整单成功。

## 5. 错误约定

业务错误继续使用 `BaseErrorCode`，不返回裸错误字符串。HTTPException 参数校验沿用现有项目包装。

| 条件 | 业务码 / 类型 | HTTP 约定 | 验收 |
|---|---|---|---|
| 非 SPACE、别名冲突、物理参数冲突、空文档切片 | 参数校验 HTTPException | 沿用现有处理器约定，响应 status_code=422 | AC-02, AC-05 |
| 空间不存在 / 无权读取 | 18000 / 18040 等现有空间错误 | 复用现有领域响应，避免泄露资源信息 | AC-02, AC-10 |
| 跨空间批量删除 | 10950 `KnowledgeFileDeleteError` | 沿用该业务码包装 | AC-06 |
| 路由缺失、初始化不完整或共享后端不可用 | 新增 10973 `KnowledgeSharedStorageUnavailableError` | `http_status=503`，保留异常日志，不回退 | AC-09 |
| 成功文件的投影未就绪或共享正文缺失 | 新增 10974 `KnowledgeSharedContentNotReadyError` | `http_status=409`，可重试，禁止空成功 | AC-09 |
| 读取期间主版本/代次变化或生命周期冲突 | 18098 `KnowledgeDocumentStateConflictError` | 沿用现有业务码包装 | AC-04, AC-09 |

10973/10974 在本地错误码目录及 v2.6.0 版本契约中未占用；实施时先登记版本契约再定义异常。
不重映射 QA 和其他入口已有错误，也不向错误响应输出原文件签名或正文。

## 6. 架构与数据边界

- Filelib 负责请求/响应编排，Knowledge 领域继续拥有文档、版本、入口和共享投影。
- 新增 Filelib 服务及必要 Knowledge 服务/Repository 能力，不在端点拼 ORM 或新增 DAO 入口。
- canonical document/version、内容代次、空间归属和租户路由是共享内容身份，不再使用旧的单个 document_id 查询代替它们。
- 新增服务复用统一权限与现有领域操作检查，不直接读取 role_access。
- 共享 schema 兼容字段、路由版本、写冻结、generation/CAS 与 schema 指纹保护保持。
- 写冻结仅拒绝写操作，不将租户冻结误当作合法读取的拒绝条件。
- 无新增表、Schema 或依赖；MySQL/DM8 的关系查询使用现有 ORM 和方言辅助能力。
- 保持 F069 业务用户作用域和 F084 原文件签名约定。本次不推广其多租户发布边界。

详细文件计划、验证批次及发布/回退约束见 [design.md](./design.md)。

## 7. 确认与后续门禁

- Discovery：已确认文件类统一 SPACE、QA 保持现状。
- Spec：已审查，用户于 2026-10-22 确认按规格实施并运行相关测试。
- Tasks：已生成并评审，按任务完成本地实现、相关回归、受控端到端及代码审查。
- 本次不部署、不迁移数据、不清理旧物理存储；真实服务验证和 DM8 证据单列，不能用模拟测试宣称已上线。
