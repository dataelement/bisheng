# 数据看板原始上传库维度

- Status: Implemented locally
- 用户授权：2026-10-15，“确认，按这个口径直接执行。”

本功能以 [requirements.md](requirements.md)、[design.md](design.md) 和 [tasks.md](tasks.md) 为实施依据。

## 规格及代码复核

- 五个中文名称与用户确认一致；复用四级组织字段ID，新增原始空间名称。
- 查询、筛选枚举、导出继续使用数据集维度；组织简称沿用原解析器。
- 原始名称批量查询置于 Repository，文件投影验证名称所属租户；不新增关系表或手写服务层SQL。
- 当前文件对账会识别新增字段差异；不修改发布和去重规则。
- 日ID固定为旧字段集合；测试使用修改前代码生成的固定摘要，避免新旧记录拆分。
- 本次未执行部署或历史回填；真实ES脚本执行和线上同步状态见 [verification.md](verification.md)。
