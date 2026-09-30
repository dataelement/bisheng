# 按文件 ID 获取原文件链接

- Feature ID: F084-file-source-link
- Created: 2026-09-08
- Status: implemented; production verification pending
- Source request: 新增按文件 ID 获取 source_full_url 的接口；复用后台 shougang.portal_base_url。

## 范围与验收

| Requirement | Acceptance | 行为 | 验证 |
|---|---|---|---|
| REQ-001 | AC-01 | GET /api/v2/filelib/file/source_url，必填正整数 file_id，返回 file_id、source_full_url；无需检索。 | V-001 API 测试 |
| REQ-002 | AC-02 | 沿用 Developer Token、路由白名单及 external_id 用户上下文；空间可读且文件 view_file 后才签发。沿用已确认的 view_file 门槛与 7 天有效期。 | V-001 拒绝路径 |
| REQ-003 | AC-03 | 引用文件只解析有效入口当前主版本；文件、空间、有效引用不存在返回既有业务错误，不能签发其他内容。 | V-002 Service + 真实入口解析器测试 |
| REQ-004 | AC-04 | 复用 shougang.portal_base_url 作为两接口的文件访问 Origin。空值回退原签名地址；非空仅接受 HTTP(S) Origin（可带端口、尾斜杠），不接受路径、凭证、查询和 fragment。路径及查询串原样保留。 | V-003 链接配置测试 |
| REQ-005 | AC-05 | 存在性检查/签名复用 retrieve；原对象缺失或存储异常返回空字符串。响应 Cache-Control: no-store；不记录完整 URL。 | V-001、V-002、既有 source Service 回归 |

不新增数据库、依赖、权限策略或修改生产配置。后台现有 YAML 编辑器可编辑该键，不新增独立前端表单。

## 兼容与风险

新接口是显式签发入口，view_file 允许获取 7 天 Bearer 链接，复用本会话已接受的 F084 行为。portal_base_url 的旧门户页面值需改为文件代理 Origin；上游 Host 必须为 sharepoint。修改返回 Origin 不解决后端到 sharepoint 的网络故障。既有 retrieve 的存储失败降级已由当前代码实现，保持该行为。
