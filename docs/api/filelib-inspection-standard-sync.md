# Filelib 点检标准 JSON 同步接口

本文档定义第三方系统将**电信智能化设备点检标准**以 JSON 形式推送至 BiSheng 的 OpenAPI 契约。服务端按 `CREATE_DEPT_ID` 分组，**一次请求会生成一个或多个 `.xlsx` 文件**（每个 distinct `CREATE_DEPT_ID` 对应 1 个文件），每个文件含与《电信智能化设备点检标准收集模版》一致的双 Sheet，并写入 Token 配置的固定知识库与目录。

> **实现状态**：已实现 `POST /api/v2/filelib/inspection-standard/sync`。

## 1. 接口概览

```http
POST /api/v2/filelib/inspection-standard/sync
Content-Type: application/json
X-Developer-Token: {plaintext-token}
```

示例 Base URL：

```text
https://{bisheng-host}/api/v2
```

### 1.0 输出文件数量

| 场景 | 生成 `.xlsx` 数量 | 说明 |
|---|---:|---|
| 全部标准同一 `CREATE_DEPT_ID` | **1 个** | 该组标准 + 关联项次写入 1 个双 Sheet 文件 |
| 标准含 N 个不同 `CREATE_DEPT_ID` | **N 个** | 每个 `CREATE_DEPT_ID` 独立生成 1 个文件 |

**要点**：

- 输出格式固定为 **`.xlsx`**（使用项目已有的 `openpyxl` 生成）。
- 每个文件均包含 Sheet `点检标准` 与 Sheet `标准项次 `。
- 各文件文件名相同，均为 `{start_date}至{end_date}.xlsx`（仅日期，不含时间），但写入不同子目录 `{Token固定目录}/{CREATE_DEPT_ID}/{start_time年份}/`。
- 成功响应 `data.files` 数组长度等于本次生成的文件数（`group_count`）。

### 1.1 处理流程

```text
JSON 请求
  → 校验 Token file_sync_rule 为「固定业务域 + 固定知识库 + 固定目录路径」
  → 校验 start_time / end_time / data
  → 校验点检标准、标准项次字段及关联关系
  → 按 check_standards.CREATE_DEPT_ID 分组
  → 按 CHECK_STANDARD_ID 将 check_standard_items 归入对应分组
  → 每个分组生成 1 个双 Sheet `.xlsx` 文件（共 1～N 个，N = distinct CREATE_DEPT_ID 数）
  → 文件名均为 `{start_date}至{end_date}.xlsx`（由 start_time/end_time 解析出的日期部分）
  → 写入 Token 配置的知识库；目录 = Token 配置目录 / CREATE_DEPT_ID / `{start_time年份}`（不存在则创建）
  → 返回 data.files[]，长度等于生成的 .xlsx 文件数
```

调用成功表示**一个或多个** `.xlsx` 文件已生成并进入知识库异步处理队列，**不表示** Excel 解析已完成。

### 1.2 与 Excel 模板的对应关系

每个分组生成的 Excel 均包含两个 Sheet：

| Sheet 序号 | Sheet 名称 | 分组内数据来源 | 第 1 行 | 第 2 行起 |
|---:|---|---|---|---|
| 1 | `点检标准` | 该组 `check_standards` | 中文列名 | 数据行 |
| 2 | `标准项次 ` | 该组 `check_standard_items` | 中文列名 | 数据行 |

**约定**：

- JSON 对象字段名须与 §4 英文字段 key **完全一致**（与收集模版英文列名行相同，含 `CRITERI`、`ENTRY_OINT_NO` 拼写）；生成 Excel **不写入**英文列名行。
- 服务端生成 Excel 时自动写入第 1 行中文表头，调用方**只需**在 JSON 中提供数据行。
- 空值统一写空单元格；数值字段在 JSON 中可用 number，写入 Excel 时按模板列类型序列化。

### 1.3 Token 配置约束（硬性要求）

本接口**仅**支持固定 Token 规则，保存与运行时均须满足：

| 配置项 | 要求 |
|---|---|
| `business_domain.mode` | 必须为 `fixed`，且 `code` 已配置 |
| `target_space.mode` | 必须为 `fixed`，且 `knowledge_id` 已配置 |
| 目标目录 | 必须配置固定目录：使用 `target_space.folder_id` **或** `target_space.folder_path` 之一；两者皆空视为未配置目录 |
| 动态规则 | `business_domain.dynamic_source`、`target_space.dynamic_source` 必须为 `null`；不支持按部门/责任人动态解析 |

若 Token 规则不满足上述约束，返回 HTTP `403`、业务码 `19915`（见 §7.1）。

其他上线条件与 [Filelib 统一文件同步接口 §1.1、§2](./filelib-file-sync.md) 相同：Token 启用、路由白名单、绑定用户对目标空间及 `{folder_path}/{CREATE_DEPT_ID}/{年份}` 具备 `upload_file` 权限。

---

## 2. 分组与入库规则

### 2.1 分组逻辑

1. **标准分组**：将 `data.check_standards` 按 `CREATE_DEPT_ID` 分组（去首尾空白后作为分组 key）。
2. **项次分组**：将 `data.check_standard_items` 按 `CHECK_STANDARD_ID` 关联到标准行，再归入该标准所在 `CREATE_DEPT_ID` 分组。
3. **一组成文件**：同一 `CREATE_DEPT_ID` 分组内的标准与项次写入**同一个** Excel 文件。

示例：

```text
CREATE_DEPT_ID = DEPT-A
  check_standards: [std-001, std-002]
  check_standard_items: [item for std-001, item for std-002]
  → 生成 1 个 Excel，写入 .../DEPT-A/{start}-{end}.xlsx

CREATE_DEPT_ID = DEPT-B
  check_standards: [std-003]
  check_standard_items: [item for std-003]
  → 生成 1 个 Excel，写入 .../DEPT-B/{start}-{end}.xlsx
```

### 2.2 入库路径

| 层级 | 来源 | 说明 |
|---|---|---|
| 知识库 | Token `target_space.knowledge_id` | 固定目标知识空间 |
| 父目录 | Token `target_space.folder_path` 或 `folder_id` 解析出的目录 | Token 配置的固定路径 |
| 部门目录 | `CREATE_DEPT_ID` | 在父目录下查找或创建同名文件夹 |
| 年份目录 | `start_time` 解析出的四位年份 | 在部门目录下，如 `2026` |
| 文件 | `{start_date}至{end_date}.xlsx` | 写入上述年份目录 |

完整路径示意：

```text
{Token 固定知识库} / {Token 固定目录} / {CREATE_DEPT_ID} / {start_time年份} / {start_date}至{end_date}.xlsx
```

同一请求内，不同 `CREATE_DEPT_ID` 分组文件名相同，但位于不同子目录，互不冲突。

### 2.3 文件名规则

| 字段 | 规则 |
|---|---|
| 扩展名 | 固定 `.xlsx` |
| 文件名 | `{start_date}至{end_date}.xlsx` |
| 日期格式化 | 取 `start_time`、`end_time` 解析后的**日期部分**（`YYYY-MM-DD`），中间用「至」连接，不含时分秒；示例：`2026-08-01至2026-08-14.xlsx` |

### 2.4 服务端自动生成的同步元数据

调用方**无需**传入 `external_file_id`、文件名、部门、责任人等参数。

| 字段 | 生成规则 |
|---|---|
| `file_name` | 各分组均为 `{start_date}至{end_date}.xlsx`（见 §2.3） |
| `external_file_id` | 按 `CREATE_DEPT_ID` + 时间窗口 + 内容摘要生成，每组独立 |
| 责任人 / 主责单位 | 默认 Token 绑定用户及其主部门 |

分类、业务域、目标知识库均由 Token `file_sync_rule` 固定配置决定。

---

## 3. 请求体

### 3.1 顶层结构

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `start_time` | string | 是 | 本次推送数据的**开始时间**。ISO 8601，推荐 `YYYY-MM-DDTHH:mm:ss` 或 `YYYY-MM-DD HH:mm:ss`。 |
| `end_time` | string | 是 | 本次推送数据的**结束时间**。格式同 `start_time`，须 `end_time >= start_time`。 |
| `data` | object | 是 | 点检业务数据，见 §3.2。 |

### 3.2 `data` 对象

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `check_standards` | array | 是 | 点检标准列表，对应 Excel Sheet `点检标准`。至少 1 条。 |
| `check_standard_items` | array | 是 | 标准项次列表，对应 Excel Sheet `标准项次 `。至少 1 条。 |

---

## 4. 字段定义

### 4.1 `data.check_standards[]` — 点检标准

JSON 字段 key 定义如下（生成 Excel 时不写入英文列名行，列顺序与下表一致）：

| JSON 字段 | 中文名 | 类型 | 长度 | 必填 | 说明 |
|---|---|---|---:|---:|---|
| `CREATE_DEPT_ID` | 设备所属单位 | string | 128 | **是** | 分组 key；决定入库子目录名。 |
| `CHECK_STANDARD_ID` | 点检标准编号 | string | 12 | 是 | 长度 12；全请求内不可重复。 |
| `DEVICE_NAME` | 分部设备中文名称 | string | 100 | 是 | 与设备 9 位码中文名称一致。 |
| `STANDARD_TYPE` | 标准类别 | string | 32 | 是 | 小代码，如 `01-常规点检`、`02-精密点检`。 |
| `OIL_PART_NO` | 油脂料号 | string | 20 | 否 | 标准类别为补充油/更换油时可选。 |
| `CHECK_ITEM_NAME` | 点检项目名称 | string | 50 | 是 | 对应项次的检测点/部位/项目。 |
| `DEVICE_STATUS` | 设备状态 | string | 16 | 是 | 小代码：`0-不限定`、`1-运转`、`2-停止`。 |
| `ENFORCE_CODE` | 实施方 | string | 16 | 是 | 小代码，如 `1-点检`。 |
| `SAFETY_BOARD` | 安全挂牌 | string | 8 | 是 | `N-否` / `Y-是`。 |
| `CHECK_PERIOD` | 实施周期 | string | 32 | 是 | 文本数字；非周期填 `"0"`。JSON 传 number 时服务端自动转为 string。 |
| `PERIOD_UNIT` | 周期单位 | string | 8 | 是 | 小代码：`H/S/D/W/M/Y/N/F` 等。 |
| `INTERFACE_SYSTEM` | 系统接口 | string | 16 | 是 | 小代码，如 `1-智能点检系统`。 |
| `NEXT_SCHE_DATE` | 下次排程日期 | string | 100 | 是 | 建议 `YYYY-MM-DD`；服务端不做格式校验。 |
| `MAINTAIN_REASON` | 维护原因 | string | 50 | 是 | 如 `初始建立`。 |
| `DEVICE_MAINTAIN_JOB_ID` | 点检员岗号 | string | 10 | 是 | |
| `REC_CREATOR` | 点检员工号 | string | 10 | 是 | |
| `REC_CREATOR_NAME` | 点检员姓名 | string | 10 | 是 | |

### 4.2 `data.check_standard_items[]` — 标准项次

| JSON 字段 | 中文名 | 类型 | 长度 | 必填 | 说明 |
|---|---|---|---:|---:|---|
| `CHECK_STANDARD_ID` | 点检标准编号 | string | 12 | 是 | 必须存在于 `check_standards` 中，通过该字段归入对应 `CREATE_DEPT_ID` 分组。 |
| `CHECK_STANDARD_SEQ_NO` | 点检标准项次 | string | 100 | 是 | 同一标准下唯一；服务端不做格式校验。 |
| `CONTENT` | 内容 | string | 50 | 是 | 项次描述。 |
| `CHECK_WAY` | 点检方法 | string | 16 | 是 | 小代码，如 `1-五感`。 |
| `LUBRIC_WAY` | 润滑方式 | string | 16 | 是 | 小代码，如 `0-无`。 |
| `LUBRIC_POINT` | 润滑点数 | string | 32 | 否 | 润滑标准时必填，如 `"1"`～`"100"`。JSON 传 number 时服务端自动转为 string。 |
| `MANAGE_CONTROL_MODE` | 管理控别 | string | 16 | 是 | 小代码，如 `0-无`。 |
| `MANAGE_TYPE` | 管理类别 | string | 16 | 否 | 小代码。 |
| `DATA_TYPE` | 数据类别 | string | 16 | 是 | `10-定性` / `20-定量` / `30-定量做倾向分析`。 |
| `CRITERI` | 标准 | string | 100 | 是 | 模板列名为 `CRITERI`（非 CRITERIA）。 |
| `UOM` | 计量单位 | string | 8 | 条件 | 定量时必填。 |
| `QLTY_TOP` | 上限 | string | 32 | 条件 | 定量时可填；不带单位。JSON 传 number 时服务端自动转为 string。 |
| `QLTY_BOTTOM` | 下限 | string | 32 | 条件 | 定量时可填；不带单位。JSON 传 number 时服务端自动转为 string。 |
| `ALARM_SETTINGS` | 报警设置 | string | 100 | 否 | |
| `STATUTORY_REQ` | 法定要求 | string | 16 | 是 | 小代码，如 `0-无`。 |
| `EQUIPMENT_NAME` | 装置名称 | string | 100 | 否 | |
| `LUBRIC_PART` | 润滑部位 | string | 100 | 否 | |
| `DISTRIBUTOR_NO` | 分配器编号 | string | 32 | 否 | |
| `ENTRY_OINT_NO` | 入机点编号 | string | 32 | 否 | 模板列名为 `ENTRY_OINT_NO`。 |
| `LUBRIC_POINT_MARK` | 润滑点标识 | string | 32 | 否 | |
| `NOZZLE_SPECIFICATION` | 油嘴规格 | string | 32 | 否 | |
| `FUELING_TOOLS` | 加油工具 | string | 32 | 否 | |
| `OIL_NO` | 油脂牌号 | string | 32 | 否 | |
| `SINGLE_INJECTION_VOLUME` | 单点注入量 | string | 32 | 否 | |
| `TOTAL_INJECTION_VOLUME` | 合计注入量 | string | 32 | 否 | |
| `LUBRIC_EFFECT_JUDGE_CRITERIA` | 润滑效果判断基准 | string | 100 | 否 | |
| `TECH_MAJOR_PIC` | 技术专业负责人 | string | 32 | 否 | |
| `RESPONSIBILITY_TEAM` | 责任班组 | string | 32 | 否 | |
| `LUBRIC_PIC` | 润滑负责人 | string | 32 | 否 | |
| `OIL_PROPERTY` | 油脂属性 | string | 16 | 否 | 小代码。 |

---

## 5. 业务校验规则

除字段类型/长度外，服务端还应校验：

| 规则 | 说明 |
|---|---|
| Token 规则 | 业务域、目标空间均为 `fixed`，且目标目录已配置（§1.3）。 |
| 时间窗口 | `start_time`、`end_time` 可解析且 `end_time >= start_time`。 |
| `CREATE_DEPT_ID` 必填 | 每条 `check_standards` 均须非空；缺失或纯空白返回 `19916`。 |
| 标准编号唯一 | 全请求内 `CHECK_STANDARD_ID` 不可重复。 |
| 项次关联 | 每条 `check_standard_items.CHECK_STANDARD_ID` 须出现在 `check_standards` 中。 |
| 项次分组一致 | 项次仅通过 `CHECK_STANDARD_ID` 归入对应标准所在 `CREATE_DEPT_ID` 分组；不允许孤儿项次。 |
| 项次序号唯一 | 同一 `CHECK_STANDARD_ID` 下 `CHECK_STANDARD_SEQ_NO` 不可重复。 |
| 字段类型 | `check_standards`、`check_standard_items` 中所有业务字段均为 **string**；为兼容历史对接，JSON 中的 integer/number 会在入库前自动转为 string（如 `CHECK_PERIOD: 1` → `"1"`）。 |
| 定量字段 | `DATA_TYPE` 为 `20-定量` 或 `30-定量做倾向分析` 时，建议校验 `UOM` 及上下限（`QLTY_TOP` / `QLTY_BOTTOM` 字符串）至少一项有值。 |
| 数组非空 | `check_standards`、`check_standard_items` 均至少 1 条；每个 `CREATE_DEPT_ID` 分组内两项均非空。 |
| 目录名合法 | `CREATE_DEPT_ID` 不得包含 `/`、`\` 等路径分隔符。 |

设备九位码、小代码枚举等深度校验可按对接阶段逐步启用；初版至少保证分组、结构与关联关系正确。

---

## 6. 请求示例

```bash
curl -X POST 'https://{bisheng-host}/api/v2/filelib/inspection-standard/sync' \
  -H 'Content-Type: application/json' \
  -H 'X-Developer-Token: bst_REDACTED' \
  -d '{
    "start_time": "2026-08-01T00:00:00",
    "end_time": "2026-08-14T23:59:59",
    "data": {
      "check_standards": [
        {
          "CREATE_DEPT_ID": "DEPT-A",
          "CHECK_STANDARD_ID": "270101J01D01",
          "DEVICE_NAME": "调度大厅",
          "STANDARD_TYPE": "01-常规点检",
          "CHECK_ITEM_NAME": "调度操作台综合检查",
          "DEVICE_STATUS": "1-运转",
          "ENFORCE_CODE": "1-点检",
          "SAFETY_BOARD": "N-否",
          "CHECK_PERIOD": "1",
          "PERIOD_UNIT": "W-周",
          "INTERFACE_SYSTEM": "1-智能点检系统",
          "NEXT_SCHE_DATE": "2026-05-06",
          "MAINTAIN_REASON": "初始建立",
          "DEVICE_MAINTAIN_JOB_ID": "JOB001",
          "REC_CREATOR": "E001",
          "REC_CREATOR_NAME": "张三"
        },
        {
          "CREATE_DEPT_ID": "DEPT-B",
          "CHECK_STANDARD_ID": "270101A02D01",
          "DEVICE_NAME": "核心机房",
          "STANDARD_TYPE": "01-常规点检",
          "CHECK_ITEM_NAME": "机房环境综合检查",
          "DEVICE_STATUS": "1-运转",
          "ENFORCE_CODE": "1-点检",
          "SAFETY_BOARD": "N-否",
          "CHECK_PERIOD": "1",
          "PERIOD_UNIT": "D-天",
          "INTERFACE_SYSTEM": "1-智能点检系统",
          "NEXT_SCHE_DATE": "2026-05-06",
          "MAINTAIN_REASON": "初始建立",
          "DEVICE_MAINTAIN_JOB_ID": "JOB002",
          "REC_CREATOR": "E002",
          "REC_CREATOR_NAME": "李四"
        }
      ],
      "check_standard_items": [
        {
          "CHECK_STANDARD_ID": "270101J01D01",
          "CHECK_STANDARD_SEQ_NO": "001",
          "CONTENT": "操作按钮、手柄灵活性及定位",
          "CHECK_WAY": "1-五感",
          "LUBRIC_WAY": "0-无",
          "MANAGE_CONTROL_MODE": "0-无",
          "MANAGE_TYPE": "0-无",
          "DATA_TYPE": "10-定性",
          "CRITERI": "灵活方便，定位可靠（GB 20905）",
          "STATUTORY_REQ": "0-无"
        },
        {
          "CHECK_STANDARD_ID": "270101A02D01",
          "CHECK_STANDARD_SEQ_NO": "001",
          "CONTENT": "机房温度",
          "CHECK_WAY": "2-简易仪器",
          "LUBRIC_WAY": "0-无",
          "MANAGE_CONTROL_MODE": "0-无",
          "MANAGE_TYPE": "0-无",
          "DATA_TYPE": "20-定量",
          "CRITERI": "18-27℃（通用要求）",
          "UOM": "℃",
          "QLTY_TOP": "27",
          "QLTY_BOTTOM": "18",
          "STATUTORY_REQ": "0-无"
        }
      ]
    }
  }'
```

上述示例将生成 **2 个** Excel 文件：

| CREATE_DEPT_ID | 入库路径（示意） | 文件名 |
|---|---|---|
| `DEPT-A` | `{Token目录}/DEPT-A/2026/` | `2026-08-01至2026-08-14.xlsx` |
| `DEPT-B` | `{Token目录}/DEPT-B/2026/` | `2026-08-01至2026-08-14.xlsx` |

---

## 7. 成功响应

一次请求生成 **1 个或多个** `.xlsx` 文件（按 `CREATE_DEPT_ID` 分组数决定）。响应 `data.files` 为各文件入库结果列表，长度等于 `group_count`：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data_start_time": "2026-08-01T00:00:00",
    "data_end_time": "2026-08-14T23:59:59",
    "group_count": 2,
    "files": [
      {
        "create_dept_id": "DEPT-A",
        "external_file_id": "INSPECTION-STD-DEPT-A-20260801",
        "file_id": 456,
        "file_encoding": "SGGF-POLICY-SAFETY-20260800000001",
        "knowledge_id": 118,
        "knowledge_name": "智能制造室(制造)",
        "folder_path": "点检标准/DEPT-A/2026",
        "generated_file_name": "2026-08-01至2026-08-14.xlsx",
        "status": 5,
        "check_standard_count": 1,
        "check_standard_item_count": 1
      },
      {
        "create_dept_id": "DEPT-B",
        "external_file_id": "INSPECTION-STD-DEPT-B-20260801",
        "file_id": 457,
        "file_encoding": "SGGF-POLICY-SAFETY-20260800000002",
        "knowledge_id": 118,
        "knowledge_name": "智能制造室(制造)",
        "folder_path": "点检标准/DEPT-B/2026",
        "generated_file_name": "2026-08-01至2026-08-14.xlsx",
        "status": 5,
        "check_standard_count": 1,
        "check_standard_item_count": 1
      }
    ]
  }
}
```

| 字段 | 说明 |
|---|---|
| `group_count` | 按 `CREATE_DEPT_ID` 分组的数量，等于 `files.length`。 |
| `files[]` | 各分组入库结果；字段含义同 Filelib 文件同步，并补充 `create_dept_id`、`folder_path`、组内行数。 |
| `status` | 文件处理状态，含义同 [filelib-file-sync §5](./filelib-file-sync.md)。 |

---

## 8. 错误契约

### 8.1 本接口扩展错误（建议业务码段 `19910`～`19919`）

| HTTP | 业务码 | 场景 |
|---:|---:|---|
| 400 | `19910` | 请求 JSON 结构非法；`start_time`/`end_time` 不可解析或顺序错误。 |
| 400 | `19911` | `check_standards` / `check_standard_items` 字段校验失败（类型、长度、必填）。 |
| 400 | `19912` | 项次关联失败：`CHECK_STANDARD_ID` 不存在于标准表；项次序号重复或格式错误。 |
| 400 | `19913` | Excel（`.xlsx`）生成失败（内存、模板写入异常等）。 |
| 422 | `19914` | `data` 数组为空，或某 `CREATE_DEPT_ID` 分组内标准/项次为空。 |
| 403 | `19915` | Token `file_sync_rule` 非固定业务域/固定知识库/固定目录，或未配置目标目录。 |
| 400 | `19916` | `CREATE_DEPT_ID` 缺失、为空或含非法路径字符。 |

### 8.2 复用 Filelib 同步错误

Excel 生成成功后，若某分组入库失败，沿用现有错误码（可按分组部分成功策略返回，或整单失败——实现阶段二选一并在代码中固定）：

| HTTP | 业务码 | 场景 |
|---:|---:|---|
| 403 | `19902` | 无上传权限（含 `{Token目录}/{CREATE_DEPT_ID}/{年份}` 节点）。 |
| 404 | `19903` | 固定分类/域/空间/目录不存在或失效。 |
| 409 | `19904` | 同目录下 `{start_date}至{end_date}.xlsx` 已存在且触发重复校验。 |
| 403 | `19906` | Token 未配置 `file_sync_rule`。 |

Developer Token 通用认证错误（`19801`～`19806`、`19812`）同 [filelib-openapi-interfaces §1.5](./filelib-openapi-interfaces.md)。

---

## 9. Excel 生成规格（实现参考）

每个 `CREATE_DEPT_ID` 分组独立生成 `.xlsx` 文件：

1. **Sheet 1** 名称固定为 `点检标准`；**Sheet 2** 名称固定为 `标准项次 `（含尾部空格，与模板一致）。
2. 每个 Sheet 第 1 行填中文列名（见 §4 中文名列）；第 2 行起写入该分组数据；不写入模版标题行与英文列名行。
3. Sheet1 仅含该组 `check_standards`；Sheet2 仅含该组 `check_standard_items`（通过 `CHECK_STANDARD_ID` 关联）。
4. `NEXT_SCHE_DATE` 列按**文本**写入，避免 Excel 自动日期序列化。
5. `CHECK_STANDARD_SEQ_NO` 按原值**文本**写入（服务端不再补零或校验位数）。
6. 不写入模板中的「说明_*」「智能点检标准小代码编制要求」等 Sheet。
7. 生成完成后走内部 Filelib 同步，目标目录为 `{Token固定目录}/{CREATE_DEPT_ID}/{start_time年份}`。

---

## 10. Token 配置示例

```json
{
  "category": {"code": "REPORT", "subcategory_code": "INSPECTION_STD"},
  "business_domain": {"mode": "fixed", "code": "MANUFACTURE", "dynamic_source": null},
  "target_space": {
    "mode": "fixed",
    "knowledge_id": 118,
    "folder_id": null,
    "folder_path": "点检标准",
    "dynamic_source": null
  }
}
```

运行时写入路径：`知识库 118 / 点检标准 / DEPT-A / 2026 / 2026-08-01至2026-08-14.xlsx`。

---

## 11. 幂等性与审计

- 本接口**不是**幂等接口；每组服务端生成的 `external_file_id` 仅用于回传与审计。
- `start_time` / `end_time` 写入各文件元数据扩展字段，便于检索。
- 记录 `CREATE_DEPT_ID`、分组行数、入库路径及 Token ID（不含 secret）。
- 同一 `{Token目录}/{CREATE_DEPT_ID}/{年份}/{start_date}至{end_date}.xlsx` 重复提交行为与 Filelib 重复上传策略一致。

---

## 12. 对接检查清单

- [ ] Token `file_sync_rule` 为固定业务域 + 固定知识库 + 固定目录（`folder_path` 或 `folder_id`）。
- [ ] Token 路由白名单已加入 `POST /api/v2/filelib/inspection-standard/sync`。
- [ ] 绑定用户对 `{Token目录}` 及预期 `{CREATE_DEPT_ID}` 子目录具备 `upload_file` 权限。
- [ ] 调用方每条 `check_standards` 均提供非空 `CREATE_DEPT_ID`。
- [ ] `check_standard_items.CHECK_STANDARD_ID` 与标准表一一对应。
- [ ] 联调验证：单分组、多分组、项次孤儿、Token 非 fixed 配置、目录自动创建。
- [ ] 确认各分组 Excel 在对应 `{CREATE_DEPT_ID}` 目录下可预览，Sheet1/Sheet2 表头与模板一致。

---

## 13. 参考

- 字段业务说明：模板 Sheet `说明_点检标准`、`说明_点检项次`。
- 文件入库规则：[filelib-file-sync.md](./filelib-file-sync.md)
- OpenAPI 通用约定：[filelib-openapi-interfaces.md](./filelib-openapi-interfaces.md)
