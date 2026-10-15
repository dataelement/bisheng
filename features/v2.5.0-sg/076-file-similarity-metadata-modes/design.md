# 设计说明：分组相似度规则

- Feature ID: `076-file-similarity-metadata-modes`
- Status: `implemented-local-verified`
- Created: `2026-10-15`
- 关联需求：[requirements.md](requirements.md)

## 上下文与已核对落点

路径相对于仓库根目录。

| 文件 | 当前职责与本次计划 |
|---|---|
| `src/backend/bisheng/core/config/settings.py` | `VersionManagementConf`；增加嵌套规则模型与旧参数回退 |
| `src/backend/bisheng/initdb_config.yaml` | 初始化模板；给出两组默认配置与中文说明，不更新已有数据库 |
| `src/backend/bisheng/api/v1/endpoints.py` | `/config/save`；在落库前校验版本管理配置，复用原错误协议及清缓存行为 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_version_service.py` | 缓存候选计算、发布候选、共用相似校验、ES正文和Redis分词缓存；仅局部改动，避免整文件重构 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_file_similarity_policy.py`（已新增） | 集中解析元数据、判断组别、选择有效规则；不查询数据库、不承担资源授权 |
| `src/backend/bisheng/approval/domain/services/shougang_approval_service.py` | 保持发布前置校验及候选查看权限回调；只在调用适配确有必要时修改 |
| `src/backend/scripts/backfill_file_similarity_candidates.py` | 复用新资格/分组规则，移除旧分类完整性门槛；保持dry-run和显式apply |
| `src/backend/test/knowledge/`、`src/backend/test/approval/` | 扩展已有配置、候选、版本、发布及脚本定向测试；新增测试分文件 |

前端响应结构、展示权重和既有API路径不变，原则上不改业务界面。项目要求的浏览器验收在实现阶段针对实际受影响入口执行。

## D-001 配置结构与优先级（REQ-002）

```yaml
knowledges:
  version_management:
    enabled: true
    same_metadata:
      simhash_similarity_threshold: 0.85
      enable_tfidf_refine: true
      tfidf_similarity_threshold: 0.3
    different_metadata:
      simhash_similarity_threshold: 0.85
      enable_tfidf_refine: true
      tfidf_similarity_threshold: 0.3
```

- 两组支持独立覆盖；每一字段优先级为组内显式值 > 旧平铺字段 > 默认值（`0.85 / true / 0.3`）。
- 只配置一组或只覆盖部分参数时，另一组/未填字段也按上述顺序解析；不能把显式false、0当成缺失。
- 模型中保留旧字段，`/env`既有字段和开关保持兼容。旧字段不再代表所有候选的唯一阈值。
- 保存入口验证组结构及阈值范围 `[0, 1]`，失败沿用现有 `SystemConfigInvalidError`，不写库、不清缓存。
- `enabled`保持全局版本管理开关含义，本次不新增组级开关。

## D-002 分组与独立资格判断（REQ-001、REQ-005）

- 从现有 `file_encoding`解析一级分类、业务域；二级分类读取 `file_subcategory_code`，不伪造到编码中。
- 分组比较使用去除两端空白后的标准编码，统一大小写；三个字段都非空且相同才进入一致组。
- 任一字段缺失或不相等均为不一致组；不能用双方空值相等判为一致。
- 公司匹配为独立资格门槛，保留既有约束；无法确认公司一致时不借分组放宽资格。分类缺失本身不再作为资格拒绝原因。
- 租户、库范围、成功主版本、自身/同文档排除及权限检查仍由原调用链负责。
- `_similarity_source_signature`补入二级分类，复用原有计算前后签名检查及有限重算，不新增跨文件锁协议。

## D-003 统一筛选并读取跨库正文（REQ-003）

1. 原资格和权限筛选通过后，为每个候选选择有效规则。
2. 依该候选的组执行SimHash初筛；不再要求分类和业务域相同。
3. 仅对开启复核的候选读取正文；同一次比较先汇总所需文件，按所属知识库批量读取，避免逐候选查询。
4. 共享存储保持租户路由、`content_file_id`和对应 `knowledge_ids`过滤；发布时分别读取源文件所在库与目标库，不移除库过滤来获取正文。
5. 复用既有Redis分词缓存。在一次比较集合内计算TF-IDF分数，再按候选各自阈值过滤，不按组分别构造不同IDF语料。
6. 保留既有排序：有复核分数的候选优先、按复核分数降序；关闭复核或缺正文的候选按SimHash降序排后。组别不获得额外优先级。
7. 库内最多3条、发布最多10条，限制为两组共同总额；先筛选有效候选再截取，避免无效行占额。

ES正文缺失时保留现有纯SimHash降级和日志；Redis不可用时本地分词。新功能不同时引入全文分页、权重调整或严格拒绝降级策略。

共用版本合并的默认相似校验需使用同一规则选择和已启用复核，避免推荐通过但写入校验仍按旧编码相等规则拒绝；保留既有force通道、MD5重复、同库和版本链校验。

## D-004 缓存、存量和补算（REQ-004）

- 继续使用 `knowledge_file_similarity_candidate`，不增加组别列，不重复保存可从元数据和配置推导的规则。
- 保持源文件每次刷新替换整组候选和既有 `similar_status`状态转移；已处理状态2不自动重开。
- 打开弹窗仍只读已保存候选，不在读请求中隐式执行ES全文复核或重算。
- 配置或分类修改后，存量缓存需在后续刷新/显式补算时采用新规则；本次不增加全库自动失效、双向补齐或自动调度。
- 脚本和在线计算使用同一资格口径，保留限制空间、批次和默认dry-run；本次只修改及测试脚本，不执行真实补算。

## 备选、风险与回退

- 未采用两套完全独立计算链：会造成发布/库内分组和降级逻辑漂移。
- 未采用新表保存组别：分组可推导，新表增加无必要的迁移与一致性成本。
- 候选和ES计算量可能增加；复用分词缓存，按库批量读取，不承诺未经线上验证的性能。
- 现有ES单次10000条正文分段上限仍在，本次不顺带改为全量滚动扫描。
- 回退代码无Schema变更；候选缓存不是自动回滚的业务快照，恢复旧候选需单独重算并授权。
- 现有超长服务只做必要局部适配，新增纯规则模块控制新增代码规模。

## 需求追踪与验证策略

| 设计 | Requirement | Acceptance | 主要证据层 |
|---|---|---|---|
| D-001 | REQ-002 | AC-02、AC-03 | 配置模型与保存入口测试 |
| D-002 | REQ-001、REQ-005 | AC-01、AC-09 | 参数化纯规则测试及拒绝路径 |
| D-003 | REQ-003、REQ-005 | AC-04、AC-05、AC-06、AC-09 | 服务+SQLite仓储、ES替身、发布权限回调 |
| D-004 | REQ-004 | AC-07、AC-08 | 缓存状态及脚本定向测试 |

实施后执行一次受影响模块回归和必要浏览器验收。真实MySQL/DM8、ES及生产大库性能验收单独标注；本地替身证据不能冒充线上结果。
