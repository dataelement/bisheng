# Filelib 同步文件接口文档（首钢定制化需求）

## 1. 通用约定

### 1.1 Base URL

```text
http://{bisheng-host}:7860/api/v2
```

### 1.2 通用 Header

| Header | 必填 | 说明 |
|---|---:|---|
| `X-Developer-Token` | 是 | 开发者 Token。由知识库系统为第三方调用方分配，系统据此校验调用方身份、IP 白名单、限流策略及目标知识资源写入权限。 |

本接口为 `multipart/form-data` 上传请求，额外需要：

| Header | 必填 | 说明 |
|---|---:|---|
| `Content-Type` | 是 | 固定为 `multipart/form-data`。由 HTTP 客户端在设置文件表单时自动生成 `boundary`，无需手动拼接。 |

### 1.3 通用成功响应

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status_code` | integer | 业务状态码。成功固定为 `200`。 |
| `status_message` | string | 业务状态说明。成功通常为 `SUCCESS`。 |
| `data` | any | 接口返回数据。 |

### 1.4 通用认证错误

| 业务码 | message | 说明 |
|---:|---|---|
| `19801` | `developer_token_missing` | 缺少 `X-Developer-Token`。 |
| `19802` | `developer_token_invalid` | Token 无效。 |
| `19803` | `developer_token_disabled` | Token 已禁用。 |
| `19804` | `developer_token_ip_forbidden` | 请求 IP 不允许。 |
| `19805` | `developer_token_rate_limited` | 超过限流。 |
| `19806` | `developer_token_limiter_unavailable` | 限流存储不可用。 |

---

## 2. 同步非结构化文件

### 2.1 接口

```http
POST /api/v2/filelib/file/sync
```

### 2.2 接口说明

第三方系统通过本接口将非结构化文件同步到知识库系统。接口接收文件二进制、第三方系统文件唯一标识、文件名称及主责信息，并将文件写入指定知识资源、提交解析任务。

调用方须携带开发者 Token（见 [1.2 通用 Header](#12-通用-header)）。系统根据 Token 确定调用方身份，并结合文件的主责单位、责任人信息，按 [2.6 文件分类与入库规则](#26-文件分类与入库规则) 计算目标知识库、文件编码与入库位置。

> 文件同步成功仅表示文件已进入知识库系统并提交处理，**不代表文件已经解析完成**。文件处理状态可通过「查询文件列表」接口查看。

### 2.3 请求 Header

| Header | 必填 | 说明 |
|---|---:|---|
| `X-Developer-Token` | 是 | 开发者 Token。 |
| `Content-Type` | 是 | 固定为 `multipart/form-data`。 |

### 2.4 请求参数（multipart/form-data）

请求体由**两个表单字段**组成：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `file` | file | 是 | 需要同步的非结构化文件二进制。扩展名须与 `params.file_name` 一致，且属于 [2.4.1 支持的文件格式](#241-支持的文件格式)。 |
| `params` | string | 是 | 额外参数的 JSON 字符串。字段定义见 [2.5 params 字段](#25-params-字段)。 |

### 2.4.1 支持的文件格式

本接口支持的文件扩展名与**知识库平台上传**保持一致，以 `params.file_name` 的扩展名为准（不区分大小写）。不在下列范围内的格式将被拒绝，HTTP `400`，消息形如 `file format is not supported: .zip`。

| 扩展名 | 说明 |
|---|---|
| `pdf` | PDF |
| `txt` | 纯文本 |
| `doc` / `docx` | Word |
| `ppt` / `pptx` | PowerPoint |
| `md` | Markdown |
| `html` / `htm` | 网页 |
| `xls` / `xlsx` | 表格 |

> **说明**
>
> - 格式校验在入库前执行；不支持 `.csv`、`.zip`、图片、音视频、信创格式（`wps` / `et` / `dps`）以及无扩展名文件等。
> - `file_name` 必须是**不含路径的文件名**（如 `报告.pdf`），不能包含 `/` 或 `\`。
> - 单文件大小等其他限制与平台上传相同，由服务端配置决定。

### 2.5 params 字段

`params` 是一段 JSON 字符串，反序列化后包含以下字段：

| 字段 | 名称 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| `external_file_id` | 文件 ID | string | 是 | - | 第三方系统文件唯一标识，用于校验第三方系统文件的唯一性。 |
| `file_name` | 文件名称 | string | 是 | - | 同步文件的名称（仅文件名，不含路径）。扩展名须属于 [2.4.1 支持的文件格式](#241-支持的文件格式)。 |
| `department_id` | 主责单位 ID | integer / string | 否 | 接口调用人所属部门 ID | 文件所属部门的 ID，不传时默认填入接口调用人所属部门。 |
| `responsible_person_id` | 责任人 ID | integer / string | 否 | 接口调用人 ID | 责任人的 ID（`user.external_id`），不传时默认填入接口调用人。 |
| `tags` | 标签 | string[] | 否 | `[]` | 同步到知识库文件上的标签名称列表。trim 后去空、保序去重。目标知识库已绑定标签库时：库中已有同名标签则复用并挂到文件；没有则写入该知识库绑定的第一个标签库再挂到文件。目标知识库未绑定标签库时**忽略 tags，文件仍入库**。解析完成后仍可追加 AI 自动标签。数量不限制。 |

`params` 示例：

```json
{
  "external_file_id": "SG-DOC-0001",
  "file_name": "安全管理制度.pdf",
  "department_id": "1024",
  "responsible_person_id": "EMP001",
  "tags": ["安全生产", "管理制度"]
}
```

### 2.6 文件分类与入库规则

知识库系统为调用方创建并分配 Token，根据不同 Token 区分调用方身份。系统按下表规则确定文件分类、业务口、文件编码与入库位置：

| 知识库字段 | 03 管理制度 | 04 精益项目 | 05 快速改善 | 06 管理参数 | 07 合理化建议 | 09 数智化成果 | 10 两化融合管理体系 | 11 降险成果 | 12 产品成果 | 14 服务案例 | 15 安全法律法规 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 文件名 | 文件名称 | | | | | | | | | | |
| 文件分类 | 政策制度-管理政策 | 技术规程与诊断-精益项目 | 技术规程与诊断-快速改善 | 技术规程与诊断-管理参数 | 技术规程与诊断-合理化建议 | 报告-经营管理成果 | 政策制度-管理政策 | 报告-经营管理成果 | 标准规范-产品成果 | 案例-故障诊断/协作案例 | 政策制度-国家/行业法规 |
| 业务口分类 | 各责任人所在科室对应的业务口 | 各责任人所在科室对应的业务口 | 各责任人所在科室对应的业务口 | 各责任人所在科室对应的业务口 | 各责任人所在科室对应的业务口 | 信息 | 信息 | 采购 | 营销 | 营销 | 安全 |
| 标签 | 入参 `tags` 写入目标库绑定的标签库并挂到文件；未绑定标签库时忽略。解析完成后仍可追加 AI 标签 | | | | | | | | | | |
| 上传人 | | | | | | | | | | | |
| 文件编码 | SG+文件分类+业务口 | | | | | | | | | | |
| 更新时间 | 入库时间 | | | | | | | | | | |
| 同步位置 | 根据主责单位对应部门库，文件存入根目录下 | 责任人主部门对应科室库；无科室库则写入责任人个人默认库。文件存入根目录下 | 责任人主部门对应科室库；无科室库则写入责任人个人默认库。文件存入根目录下 | 责任人主部门对应科室库；无科室库则写入责任人个人默认库。文件存入根目录下 | 责任人主部门对应科室库；无科室库则写入责任人个人默认库。文件存入根目录下 | 公共库/信息库 | 公共库/信息库 | 公共库/采购库 | 部门库/营销中心 | 部门库/营销中心 | 部门库/安全部 |

**目标空间解析（与 Token `target_space.dynamic_source` 对应）：**

- `department_id`（如 03 管理制度）：按主责单位从近到远查找部门库；同层出现多个候选时返回冲突，不随机取第一项。
- `responsible_person_id`（如 04～07）：使用责任人唯一主部门上的科室库；**无科室库时写入该责任人的个人默认知识库**（`{用户名}的知识库`，不存在则创建），**不再沿部门树回退到部门库**。个人库不存在时由接口按责任人身份创建后再入库。

### 2.7 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./安全管理制度.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0001","file_name":"安全管理制度.pdf","department_id":"1024","responsible_person_id":"EMP001","tags":["安全生产","管理制度"]}'
```

### 2.8 响应示例

同步回执（文件已入库并提交处理）：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0001",
    "file_id": 345,
    "file_encoding": "SGGF-QM-AQ-20260700000001",
    "knowledge_id": 118,
    "knowledge_name": "安全环保部-部门库",
    "status": 5,
    "tags": ["安全生产", "管理制度"]
  }
}
```

### 2.9 响应参数

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.external_file_id` | string | 第三方系统文件唯一标识，原样回传，便于调用方对账。 |
| `data.file_id` | integer | 知识库系统内的文件 ID。 |
| `data.file_encoding` | string | 文件编码，规则为 `SG+文件分类+业务口`。 |
| `data.knowledge_id` | integer | 文件落库的目标知识资源 ID。 |
| `data.knowledge_name` | string | 文件落库的目标知识资源名称。 |
| `data.status` | integer | 文件处理状态。同步刚提交时通常为 `5`（排队中）。取值见下表。 |
| `data.tags` | string[] | 实际挂到文件上的标签名称。目标库未绑定标签库、或全部被忽略时为空数组。 |

`status` 枚举：

| 值 | 说明 |
|---:|---|
| `1` | 处理中 |
| `2` | 处理成功 |
| `3` | 处理失败 |
| `4` | 重建中 |
| `5` | 排队中 |
| `6` | 解析超时 |
| `7` | 内容安全违规 |

### 2.10 错误响应

**认证错误**：见 [1.4 通用认证错误](#14-通用认证错误)。

**参数与权限错误**：

| HTTP 状态 | detail | 场景 |
|---:|---|---|
| `400` | `params must be valid JSON` | `params` 不是合法 JSON 字符串。 |
| `400` | `external_file_id must not be empty` | `params.external_file_id` 缺失或为空。 |
| `400` | `file_name must not be empty` | `params.file_name` 缺失或为空。 |
| `400` | `file_name must be a base name` | `params.file_name` 含路径分隔符（`/` 或 `\`）。 |
| `400` | `file format is not supported: .{ext}` | `params.file_name` 扩展名不在平台上传支持范围内，见 [2.4.1](#241-支持的文件格式)。 |
| `400` | `file must not be empty` | 上传文件大小为 0。 |
| `400` | `params fields are invalid` | `params.tags` 不是字符串数组。 |
| `403` | - | 无目标知识资源写入权限。 |
| `409` | `duplicate external_file_id` | `external_file_id` 已同步过，唯一性校验未通过。 |
| `422` | - | multipart 表单校验失败（缺少 `file` 或 `params`）。 |

**业务规则错误**（分类 / 知识库 / 业务口匹配失败，以业务消息返回）：

| 场景 | 返回消息 |
|---|---|
| 文件分类未在平台配置固定分类 | `行份知识管理平台不存在分类{{分类名称/二级分类名称}}` |
| 主责单位未绑定部门库（`department_id` 动态目标） | `行份知识管理平台不存在知识库{{知识库名称}}` |
| 责任人主部门未绑定科室库 | 不报错；改写入责任人个人默认知识库（不存在则创建） |
| 部门库中缺少「上传人所在科室对应的」业务口 | `行份知识管理平台的{{知识库名称}}不存在{{业务口名称}}` |
