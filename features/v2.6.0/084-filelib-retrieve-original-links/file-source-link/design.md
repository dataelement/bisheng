# 设计

采用 Endpoint → FilelibFileSourceService → Repository / Knowledge 权限与入口解析器 → FilelibRetrieveSourceService。

## 文件计划

- open_endpoints/domain/services/filelib_file_source_service.py：读取文件和所属知识资源，先校验资源读取和 view_file；调用 KnowledgeDocumentEntryResolver 验证入口/版本，构造 RetrieveSourceRef，复用链接服务。
- open_endpoints/domain/schemas/filelib.py：FileSourceUrlResp。
- open_endpoints/api/endpoints/filelib.py 与 api/dependencies.py：新增 GET 路由与依赖，复用 get_filelib_request_user；no-store。
- filelib_retrieve_source_service.py：可选配置提供器，每次解析读取一次后台配置；源链接签完后派生相对路径，组合配置 Origin。配置错误不得当作空配置。
- core/config/settings.py、initdb_config.yaml：更新 portal_base_url 语义；共用 Origin 校验。
- api/v1/endpoints.py：系统配置保存时校验该字段。
- test/open_endpoints/test_filelib_file_source_url.py、既有 source Service 测试：权限、输入、引用解析、配置及失败路径。
- docs/api/filelib-file-source-url.md、filelib-openapi-interfaces.md、filelib-retrieve.md：调用示例与代理条件。
- test/open_endpoints/test_filelib_external_user_context.py：补齐既有 retrieve 测试依赖；客户端 config.ts 仅同步 portal_base_url 注释。

REQ-001/002/005 以 V-001 API 契约验证；REQ-003 使用 V-002 真实入口解析器与 fake Repository；REQ-004 以 V-003 链接 Service 验证。不连接线上依赖；真实 MinIO GET 作为人工验证明确记录。

读取配置在 Service 中执行，Storage 不依赖业务配置；不缓存完整 URL，不重写签名查询参数。未设置配置时行为保持。配置 Origin 不带路径以保证 Nginx 转发路径与签名路径一致。

回退：撤回本次代码并恢复旧 portal_base_url 值；已签发链接仍按 7 天到期。
