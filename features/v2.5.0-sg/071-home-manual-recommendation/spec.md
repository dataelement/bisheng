# F071：首页管理员人工推荐置顶

- Status: `implemented-local-verified`
- Created: `2026-10-09`
- Spec Discovery: 用户已确认所有用户统一置顶、占用原条数、首页和更多一致；候选范围为公共库 OR 开启公开发现开关的有效库。

本功能跨门户和毕昇，单一完整规格存放于首钢项目：

- [需求与验收](../../../../首钢项目/specs/044-portal-manual-recommendation/requirements.md)
- [设计与边界](../../../../首钢项目/specs/044-portal-manual-recommendation/design.md)
- [实施任务](../../../../首钢项目/specs/044-portal-manual-recommendation/tasks.md)
- [验证记录](../../../../首钢项目/specs/044-portal-manual-recommendation/verification.md)

只扩展 F056 原排除的人工置顶能力。复用现有租户聚合配置、版本和知识身份，公共/公开知识仅输出安全展示元数据；正文和审批权限不变。实施任务包含版本契约必要扩展，不改其他 Feature 所有权。用户已确认实施，全部任务完成本地验证；未提交、未部署，DM8 实库门禁未执行。
