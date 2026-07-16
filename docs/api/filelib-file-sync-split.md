# Filelib 同步文件接口文档（首钢定制化需求 · 分接口版）

> 本文档在原「同步非结构化文件」单接口基础上，按 11 个业务分类规则拆分为 11 个独立接口。
> 每个接口对应一条固定的分类与入库规则，调用方按业务类型直接选择对应接口 URL 上传文件，无需理解 Token 与分类的隐式映射。
> 通用部分（Base URL、Header、认证、成功/错误响应、`params` 字段、`status` 枚举、文件编码规则等）统一在「1. 通用约定」中定义，各接口共享，不再重复展开。

## 目录

- [1. 通用约定](#1-通用约定)
- [2. 接口列表](#2-接口列表)
  - [2.1 同步「03 管理制度」文件](#21-同步03-管理制度文件)
  - [2.2 同步「04 精益项目」文件](#22-同步04-精益项目文件)
  - [2.3 同步「05 快速改善」文件](#23-同步05-快速改善文件)
  - [2.4 同步「06 管理参数」文件](#24-同步06-管理参数文件)
  - [2.5 同步「07 合理化建议」文件](#25-同步07-合理化建议文件)
  - [2.6 同步「09 数智化成果」文件](#26-同步09-数智化成果文件)
  - [2.7 同步「10 两化融合管理体系」文件](#27-同步10-两化融合管理体系文件)
  - [2.8 同步「11 降险成果」文件](#28-同步11-降险成果文件)
  - [2.9 同步「12 产品成果」文件](#29-同步12-产品成果文件)
  - [2.10 同步「14 服务案例」文件](#210-同步14-服务案例文件)
  - [2.11 同步「15 安全法律法规」文件](#211-同步15-安全法律法规文件)

---

## 1. 通用约定

### 1.1 Base URL

```text
http://{bisheng-host}:7860/api/v2
```

### 1.2 通用 Header

| Header | 必填 | 说明 |
|---|---:|---|
| `X-Developer-Token` | 是 | 开发者 Token。由知识库系统为第三方调用方分配，系统据此校验调用方身份、IP 白名单、限流策略及目标知识资源写入权限。 |

本组接口均为 `multipart/form-data` 上传请求，额外需要：

| Header | 必填 | 说明 |
|---|---:|---|
| `Content-Type` | 是 | 固定为 `multipart/form-data`。由 HTTP 客户端在设置文件表单时自动生成 `boundary`，无需手动拼接。 |

### 1.3 通用请求参数（multipart/form-data）

所有接口的请求体均由**两个表单字段**组成：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `file` | file | 是 | 需要同步的非结构化文件二进制。 |
| `params` | string | 是 | 额外参数的 JSON 字符串。字段定义见 [1.4 params 字段](#14-params-字段)。 |

### 1.4 params 字段

`params` 是一段 JSON 字符串，反序列化后包含以下字段：

| 字段 | 名称 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---:|---|---|
| `external_file_id` | 文件 ID | string | 是 | - | 第三方系统文件唯一标识，用于校验第三方系统文件的唯一性。 |
| `file_name` | 文件名称 | string | 是 | - | 同步文件的名称。 |
| `department` | 主责单位 | string | 否 | 接口调用人所属部门 | 文件所属部门，不传时默认填入接口调用人所属部门。 |
| `department_id` | 主责单位 ID | integer / string | 否 | 接口调用人所属部门 ID | 文件所属部门的 ID，不传时默认填入接口调用人所属部门。 |
| `responsible_person` | 责任人 | string | 否 | 接口调用人 | 文件的责任人，不传时默认填入接口调用人。 |
| `responsible_person_id` | 责任人 ID | integer / string | 否 | 接口调用人 ID | 责任人的 ID，不传时默认填入接口调用人。 |

补充校验规则：

- ID 为权威字段；同时传入 ID 和名称时，名称必须与 ID 对应的实际名称一致。
- `03` 接口指定非调用人主部门作为主责单位时，必须传 `department_id`。
- `04`、`05`、`06`、`07` 接口指定非调用人作为责任人时，必须传 `responsible_person_id`。
- `external_file_id` 与当前同步接口共同标识文件来源，系统不按该字段执行唯一性或幂等校验；重复提交会分别进入正常上传流程。

`params` 示例：

```json
{
  "external_file_id": "SG-DOC-0001",
  "file_name": "安全管理制度.pdf",
  "department": "安全环保部",
  "department_id": 1024,
  "responsible_person": "zhangsan",
  "responsible_person_id": 12
}
```

### 1.5 通用固定规则

以下规则对全部 11 个接口一致，各接口不再重复：

| 项 | 规则 |
|---|---|
| 文件名 | 取 `params.file_name`。 |
| 标签 | 跟随知识库的 AI 标签生成规则。 |
| 文件编码 | `SGGF-{一级分类编码}-{业务域编码}-{YYYYMM}{8位序号}`；序号按目标知识空间和月份计算。 |
| 更新时间 | 入库时间。 |
| 上传人 | 接口调用人。 |

> 各接口的差异仅体现在**文件分类**、**业务域分类**、**同步位置**三项，详见各接口章节。

### 1.6 通用成功响应

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

各接口同步回执 `data` 结构一致：

| 字段 | 类型 | 说明 |
|---|---|---|
| `data.external_file_id` | string | 第三方系统文件唯一标识，原样回传，便于调用方对账。 |
| `data.file_id` | integer | 知识库系统内的文件 ID。 |
| `data.file_encoding` | string | 最终文件编码，格式为 `SGGF-{一级分类编码}-{业务域编码}-{YYYYMM}{8位序号}`。 |
| `data.knowledge_id` | integer | 文件落库的目标知识资源 ID。 |
| `data.knowledge_name` | string | 文件落库的目标知识资源名称。 |
| `data.status` | integer | 文件处理状态。同步刚提交时通常为 `5`（排队中）。取值见 [1.7 status 枚举](#17-status-枚举)。 |

> 文件同步成功仅表示文件已进入知识库系统并提交处理，**不代表文件已经解析完成**。文件处理状态可通过「查询文件列表」接口查看。

### 1.7 status 枚举

| 值 | 说明 |
|---:|---|
| `1` | 处理中 |
| `2` | 处理成功 |
| `3` | 处理失败 |
| `4` | 重建中 |
| `5` | 排队中 |
| `6` | 解析超时 |
| `7` | 内容安全违规 |

### 1.8 通用认证错误

| 业务码 | message | 说明 |
|---:|---|---|
| `19801` | `developer_token_missing` | 缺少 `X-Developer-Token`。 |
| `19802` | `developer_token_invalid` | Token 无效。 |
| `19803` | `developer_token_disabled` | Token 已禁用。 |
| `19804` | `developer_token_ip_forbidden` | 请求 IP 不允许。 |
| `19805` | `developer_token_rate_limited` | 超过限流。 |
| `19806` | `developer_token_limiter_unavailable` | 限流存储不可用。 |

### 1.9 通用参数与权限错误

| HTTP 状态 | detail | 场景 |
|---:|---|---|
| `400` | `params must be valid JSON` | `params` 不是合法 JSON 字符串。 |
| `400` | `external_file_id must not be empty` | `params.external_file_id` 缺失或为空。 |
| `400` | `file_name must not be empty` | `params.file_name` 缺失或为空。 |
| `403` | - | 无目标知识资源写入权限。 |
| `404` | - | 人员、部门、分类、业务域、目标知识空间或绑定配置不存在。 |
| `409` | `duplicate file content or name` | 现有知识上传校验判定文件内容或名称重复。 |
| `422` | - | multipart 表单校验失败（缺少 `file` 或 `params`）。 |

### 1.10 通用业务规则错误

分类 / 知识库 / 业务域匹配失败时，以业务消息返回：

| 场景 | 返回消息 |
|---|---|
| 文件分类未在平台配置固定分类 | `首钢股份知识管理平台不存在分类{{分类名称/二级分类名称}}` |
| 主责单位或责任人未绑定知识库 | `首钢股份知识管理平台不存在知识库{{知识库名称}}` |
| 目标知识空间未绑定所需业务域 | `首钢股份知识管理平台的{{知识库名称}}不存在{{业务域名称}}` |

> 二级分类名称中的 `/` 是名称本身的一部分，例如 `故障诊断/协作案例` 和 `国家/行业法规`，不表示备选分类或第三级分类。

---

## 2. 接口列表

> 下列 11 个接口的**请求 Header**、**请求参数**、**`params` 字段**、**成功响应结构**、**`status` 枚举**、**认证/参数/权限/业务规则错误**均遵循「1. 通用约定」。
> 各接口章节仅描述其**固定分类规则**与**示例**。

### 2.1 同步「03 管理制度」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/03
```

#### 接口说明

第三方系统通过本接口将「03 管理制度」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 政策制度-管理政策 |
| 业务域分类 | 各责任人所在科室对应的业务域（运行时按责任人科室动态解析） |
| 同步位置 | 根据主责单位对应部门库，文件存入根目录下（运行时按主责单位动态解析） |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/03' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./安全管理制度.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0301","file_name":"安全管理制度.pdf","department":"安全环保部","department_id":1024,"responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0301",
    "file_id": 345,
    "file_encoding": "SGGF-<政策制度编码>-<责任人业务域编码>-20260700000001",
    "knowledge_id": 118,
    "knowledge_name": "安全环保部-部门库",
    "status": 5
  }
}
```

---

### 2.2 同步「04 精益项目」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/04
```

#### 接口说明

第三方系统通过本接口将「04 精益项目」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 技术规程与诊断-精益项目 |
| 业务域分类 | 各责任人所在科室对应的业务域（运行时按责任人科室动态解析） |
| 同步位置 | 根据责任人所属科室所对应的科室库，文件存入根目录下（运行时按责任人科室动态解析） |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/04' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./精益项目改善报告.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0401","file_name":"精益项目改善报告.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0401",
    "file_id": 346,
    "file_encoding": "SGGF-<技术规程与诊断编码>-<责任人业务域编码>-20260700000001",
    "knowledge_id": 121,
    "knowledge_name": "<责任人科室>-科室库",
    "status": 5
  }
}
```

---

### 2.3 同步「05 快速改善」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/05
```

#### 接口说明

第三方系统通过本接口将「05 快速改善」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 技术规程与诊断-快速改善 |
| 业务域分类 | 各责任人所在科室对应的业务域（运行时按责任人科室动态解析） |
| 同步位置 | 根据责任人所属科室所对应的科室库，文件存入根目录下（运行时按责任人科室动态解析） |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/05' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./快速改善案例.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0501","file_name":"快速改善案例.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0501",
    "file_id": 347,
    "file_encoding": "SGGF-<技术规程与诊断编码>-<责任人业务域编码>-20260700000001",
    "knowledge_id": 121,
    "knowledge_name": "<责任人科室>-科室库",
    "status": 5
  }
}
```

---

### 2.4 同步「06 管理参数」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/06
```

#### 接口说明

第三方系统通过本接口将「06 管理参数」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 技术规程与诊断-管理参数 |
| 业务域分类 | 各责任人所在科室对应的业务域（运行时按责任人科室动态解析） |
| 同步位置 | 根据责任人所属科室所对应的科室库，文件存入根目录下（运行时按责任人科室动态解析） |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/06' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./管理参数配置表.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0601","file_name":"管理参数配置表.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0601",
    "file_id": 348,
    "file_encoding": "SGGF-<技术规程与诊断编码>-<责任人业务域编码>-20260700000001",
    "knowledge_id": 121,
    "knowledge_name": "<责任人科室>-科室库",
    "status": 5
  }
}
```

---

### 2.5 同步「07 合理化建议」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/07
```

#### 接口说明

第三方系统通过本接口将「07 合理化建议」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 技术规程与诊断-合理化建议 |
| 业务域分类 | 各责任人所在科室对应的业务域（运行时按责任人科室动态解析） |
| 同步位置 | 根据责任人所属科室所对应的科室库，文件存入根目录下（运行时按责任人科室动态解析） |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/07' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./合理化建议汇总.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0701","file_name":"合理化建议汇总.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0701",
    "file_id": 349,
    "file_encoding": "SGGF-<技术规程与诊断编码>-<责任人业务域编码>-20260700000001",
    "knowledge_id": 121,
    "knowledge_name": "<责任人科室>-科室库",
    "status": 5
  }
}
```

---

### 2.6 同步「09 数智化成果」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/09
```

#### 接口说明

第三方系统通过本接口将「09 数智化成果」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 报告-经营管理成果 |
| 业务域分类 | 信息 |
| 同步位置 | 公共库/信息库 |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/09' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./数智化转型成果报告.pdf' \
  -F 'params={"external_file_id":"SG-DOC-0901","file_name":"数智化转型成果报告.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-0901",
    "file_id": 350,
    "file_encoding": "SGGF-<报告编码>-<信息业务域编码>-20260700000001",
    "knowledge_id": 130,
    "knowledge_name": "公共库-信息库",
    "status": 5
  }
}
```

---

### 2.7 同步「10 两化融合管理体系」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/10
```

#### 接口说明

第三方系统通过本接口将「10 两化融合管理体系」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 政策制度-管理政策 |
| 业务域分类 | 信息 |
| 同步位置 | 公共库/信息库 |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/10' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./两化融合管理手册.pdf' \
  -F 'params={"external_file_id":"SG-DOC-1001","file_name":"两化融合管理手册.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-1001",
    "file_id": 351,
    "file_encoding": "SGGF-<政策制度编码>-<信息业务域编码>-20260700000001",
    "knowledge_id": 130,
    "knowledge_name": "公共库-信息库",
    "status": 5
  }
}
```

---

### 2.8 同步「11 降险成果」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/11
```

#### 接口说明

第三方系统通过本接口将「11 降险成果」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 报告-经营管理成果 |
| 业务域分类 | 采购 |
| 同步位置 | 公共库/采购库 |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/11' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./降险成果报告.pdf' \
  -F 'params={"external_file_id":"SG-DOC-1101","file_name":"降险成果报告.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-1101",
    "file_id": 352,
    "file_encoding": "SGGF-<报告编码>-<采购业务域编码>-20260700000001",
    "knowledge_id": 131,
    "knowledge_name": "公共库-采购库",
    "status": 5
  }
}
```

---

### 2.9 同步「12 产品成果」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/12
```

#### 接口说明

第三方系统通过本接口将「12 产品成果」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 标准规范-产品成果 |
| 业务域分类 | 营销 |
| 同步位置 | 部门库/营销中心 |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/12' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./产品成果说明书.pdf' \
  -F 'params={"external_file_id":"SG-DOC-1201","file_name":"产品成果说明书.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-1201",
    "file_id": 353,
    "file_encoding": "SGGF-<标准规范编码>-<营销业务域编码>-20260700000001",
    "knowledge_id": 140,
    "knowledge_name": "营销中心-部门库",
    "status": 5
  }
}
```

---

### 2.10 同步「14 服务案例」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/14
```

#### 接口说明

第三方系统通过本接口将「14 服务案例」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 案例-故障诊断/协作案例 |
| 业务域分类 | 营销 |
| 同步位置 | 部门库/营销中心 |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/14' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./客户服务案例.pdf' \
  -F 'params={"external_file_id":"SG-DOC-1401","file_name":"客户服务案例.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-1401",
    "file_id": 354,
    "file_encoding": "SGGF-<案例编码>-<营销业务域编码>-20260700000001",
    "knowledge_id": 140,
    "knowledge_name": "营销中心-部门库",
    "status": 5
  }
}
```

---

### 2.11 同步「15 安全法律法规」文件

#### 接口

```http
POST /api/v2/filelib/file/sync/15
```

#### 接口说明

第三方系统通过本接口将「15 安全法律法规」类非结构化文件同步到知识库系统。接口接收文件二进制及 `params`（见 [1.4 params 字段](#14-params-字段)），按本接口固定的分类规则写入指定知识资源并提交解析任务。

#### 固定分类规则

| 项 | 取值 |
|---|---|
| 文件分类 | 政策制度-国家/行业法规 |
| 业务域分类 | 安全 |
| 同步位置 | 部门库/安全部 |

#### 请求示例

```bash
curl -X POST 'http://127.0.0.1:7860/api/v2/filelib/file/sync/15' \
  -H 'X-Developer-Token: bst_xxx' \
  -F 'file=@./安全生产法.pdf' \
  -F 'params={"external_file_id":"SG-DOC-1501","file_name":"安全生产法.pdf","responsible_person":"zhangsan","responsible_person_id":12}'
```

#### 响应示例

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "external_file_id": "SG-DOC-1501",
    "file_id": 355,
    "file_encoding": "SGGF-<政策制度编码>-<安全业务域编码>-20260700000001",
    "knowledge_id": 141,
    "knowledge_name": "安全部-部门库",
    "status": 5
  }
}
```
