# 按文件 ID 获取原文件地址

`GET /api/v2/filelib/file/source_url`

无需执行向量检索，按文件 ID 获取与 `/retrieve` 的 `source_full_url` 同语义的原文件 GET 预签名地址。每次重新签发，有效期 7 天。

## 请求

必填 Header：`X-Developer-Token`。Token 的路由白名单必须允许 `GET /api/v2/filelib/file/source_url`；新增接口不会自动扩展已有 Token 授权。

| 参数 | 必填 | 说明 |
|---|---|---|
| `file_id` | 是 | 正整数 `KnowledgeFile.id`，即 `/retrieve` 返回的 `document_id`；不是逻辑文档 ID 或版本 ID。 |
| `external_id` | 否 | 与其他 Filelib 查询接口一致：指定业务用户；未传则使用 Token 绑定用户。 |

```bash
curl --get 'https://bisheng.example.com/api/v2/filelib/file/source_url' \
  --header 'X-Developer-Token: <your-token>' \
  --data-urlencode 'file_id=123' \
  --data-urlencode 'external_id=EMP001'
```

## 返回

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file_id": 123,
    "source_full_url": "https://files.example.com/bisheng/original/123.pdf?X-Amz-Expires=604800&X-Amz-Signature=REDACTED"
  }
}
```

成功响应包含 `Cache-Control: no-store`。没有文件原对象，或 MinIO 检查/签名失败时，`source_full_url` 为空字符串，沿用当前 retrieve 的降级语义。调用方应检查业务码及 URL 非空，不缓存或记录完整签名。

参数缺失、非正整数、非法 `external_id` 返回 HTTP 422。文件不存在、目录、失效引用、所属资源已删除使用既有 `18020` 业务错误；文件无 `view_file` 使用既有 `18040` 业务错误；空间读取失败和 Token 错误沿用现有异常契约。应同时检查 HTTP 状态和响应业务码，业务拒绝不一定是 HTTP 403。

## 权限与引用文件

服务先校验所属知识资源读取权限及入口文件 `view_file`。普通文件使用其原对象；有效发布/共享引用通过现有入口解析器解析当前主版本。无权、无效引用不会调用原文件签名服务。

沿用 F084 已确认的访问约定：不额外要求 `download_file`，不经过门户下载额度、水印和审计。签名 URL 是 Bearer 凭证，持有者在 7 天内可不带 Developer Token 直接 GET；撤销用户权限不会提前撤销已发出的 URL。

## 后台访问地址配置

在后台「系统配置」YAML 中编辑：

```yaml
shougang:
  portal_base_url: "https://files.example.com:9443"
```

该键现用于原文件访问 Origin，新接口和 `/retrieve` 共用。允许 HTTP(S)、端口和末尾 `/`；不能带 `/workspace` 等路径、用户密码、查询串或 fragment。为空/未配置时保留 MinIO 生成的完整地址。已有部署需在后台编辑保存，修改初始化 YAML 不会覆盖数据库配置。

生成规则：先用 MinIO `sharepoint` 签名，保留原对象路径和完整查询串，再用配置 Origin 替换返回地址的协议/主机。代理转发到同一 MinIO 时必须恢复签名使用的 Host，例如签名使用 `sharepoint: minio.internal:9000`，则配置 `proxy_set_header Host minio.internal:9000;`。不要在该 Host 中带协议，也不要改变签名路径和查询参数。

此配置只改变调用方访问地址，后端仍需能访问 `sharepoint` 以完成 SDK 的 bucket region 查询。此前 Nginx bucket 根路径问题仍需通过匹配 `/(bisheng|skm-bisheng|tmp-dir)(?:/|$)` 等部署规则解决。
