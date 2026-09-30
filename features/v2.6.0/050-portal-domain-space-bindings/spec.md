# Feature: 门户业务域知识空间多绑定

**关联 PRD**: 门户后台业务域配置
**优先级**: P1
**所属版本**: v2.6.0

---

## 1. 概述与用户故事

作为 **门户管理员**，
我希望 **一个业务域可以绑定多个公共/部门知识空间，且知识空间能被多个业务域复用**，
以便 **门户前台可以按业务域聚合知识资源，并为后续空间业务分类能力提供数据基础**。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 门户管理员 | 在业务域编辑页选择多个公共/部门知识空间并保存 | 业务域配置持久化多个 `space_ids` |
| AC-02 | 门户管理员 | 将同一知识空间绑定到多个业务域 | BiSheng `knowledge.business_domain_codes` 包含多个业务域 `code` |
| AC-03 | 门户管理员 | 取消某业务域与知识空间的绑定并保存 | 该空间的 `business_domain_codes` 移除对应 `code`，保留其他业务域 `code` |
| AC-04 | 门户管理员 | 打开业务域编辑页加载空间候选项 | 公共空间和部门空间分组展示，未绑定空间返回 `business_domain_codes: []` |
| AC-05 | 门户管理员 | BiSheng 同步失败时保存业务域配置 | 门户配置不落库，并返回保存失败提示 |

---

## 3. 边界情况

- 当业务域 `code` 为空时，该业务域不能参与 BiSheng `business_domain_codes` 同步。
- 当知识空间没有绑定任何业务域时，接口输出空列表 `[]`。
- 当 BiSheng 同步成功但门户本地保存失败时，需要尽力补偿回旧映射；补偿失败必须记录日志并返回错误。
- **不支持**：新增业务域独立 ID。
- **不支持**：改变文件自身的 `business_domain_code` 上传/检索规则。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 业务域列表字段落库位置 | A: `knowledge.business_domain_codes` / B: `knowledge_space_scope.business_domain_codes` | 选 A | 知识空间主体复用 `knowledge` 表，字段只对 `type=SPACE` 有业务含义 |
| AD-02 | 字段内容 | A: 业务域 `code` / B: 业务域名称 / C: 业务域 ID | 选 A | 现有业务域编码已用于文件分类和统计，稳定且适合后续逻辑判断 |
| AD-03 | 同步策略 | A: 全量重算 / B: 增量更新 | 选 A | 可避免业务域改名、删除、批量保存后残留脏数据 |
| AD-04 | 失败策略 | A: 强一致失败阻断保存 / B: 弱一致警告 | 选 A | 防止门户配置和 BiSheng 空间字段不一致 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

- 表：`knowledge`
- 新增列：`business_domain_codes`
- 类型：`JsonType`
- 应用层默认值：`[]`
- 业务含义：仅当 `knowledge.type == KnowledgeTypeEnum.SPACE.value` 时表示该知识空间被哪些门户业务域绑定。

### Domain 模型 / DTO

- `KnowledgeBase.business_domain_codes: Optional[List[str]]`
- `KnowledgeSpaceInfoResp.business_domain_codes: List[str]`
- 门户同步请求：

```json
{
  "bindings": [
    { "space_id": 1001, "business_domain_codes": ["PP", "QM"] },
    { "space_id": 1002, "business_domain_codes": [] }
  ]
}
```

---

## 6. API 契约

### 端点列表

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| PUT | `/api/v1/knowledge/shougang-portal/spaces/business-domain-codes` | 批量同步空间绑定的业务域编码列表 | 是 |

### 成功响应

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "updated": 2
  }
}
```

---

## 7. Service 层逻辑

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `sync_shougang_portal_space_business_domain_codes` | 空间 ID 到业务域编码列表 | 更新数量 | 校验空间存在且为知识空间，标准化编码，批量更新 `business_domain_codes` |

---

## 8. 前端设计

### 门户后台

- 业务域编辑弹窗将单选空间改为分组复选列表。
- 分组包含公共空间和部门空间。
- 已选空间以标签形式展示，可单独取消。

---

## 9. 测试策略

- BiSheng 后端：覆盖同步接口、多业务域编码、空列表清除、非知识空间过滤。
- 门户后端：覆盖保存前同步成功、同步失败不落库、`space-options` 返回字段。
- 门户前端：覆盖多选草稿校验、分组过滤、输出多个 `space_ids`。
