# Design: 模型名称首尾空格兼容（F065）

> **本文档定位 — 实现方案 / 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**
> - `design.md`（本文）回答 **为什么这么实现**、挂在哪、19802 实际从哪来
>
> **关联**: [spec.md](./spec.md) · PRD《3.0 beta2》§5.7
> **版本**: v3.0.0-beta1
> **最后更新**: 2026-09-10

---

## 1. 目标与非目标

- **目标**：管理后台添加 / 更新模型时，用户在「模型名称」前后多敲的空白不再进入数据库，也不再作为厂商 `model` 参数发出去。保存失败时走原有空名 / 重名校验，而不是厂商拒识或租户可见性错误。
- **非目标**：见 [spec.md](./spec.md) 范围边界。实现上额外钉死：
  - **不改 19802**。它是租户可见性错误，不是「名称带空格」的专用码。
  - **不写存量清洗脚本**。脏行再保存一次即可。
  - **不扩到服务商名 / 展示名**。PRD 只点了「模型名称」。

---

## 2. 关键约束

遵循 `docs/constitution.md` C1–C7。本功能特有：

- `llm_model.model_name` 是发给厂商的真实模型 ID，不是展示文案。实例化时写进 `params['model']`（`llm/domain/llm/llm.py` `_get_default_params`，embedding / asr / tts / rerank 同类）。
- 同一服务商下 `(server_id, model_name)` 有唯一约束 `server_model_uniq`。必须**先去空格再判重**，否则 `gpt-4` 与 ` gpt-4 ` 会写成两行，厂商侧却是同一个模型。
- 服务商配置里的密钥 / endpoint 已经在 `LLMService.strip_config_whitespace` 去过首尾空白；模型名称是同一类「粘贴多带空格」问题，写入契约应落在后端，不能只靠页面。
- Alembic 禁止数据回填（C2 / 迁移规则）。存量脏名不是本 Feature 的迁移对象。

---

## 3. 方案对比与选定

### 决策 1：去空格挂在哪一层

- **备选**：
  - A. 只改前端：`ModelConfig.handleSave` 提交前对每条 `model_name` 做 `trim()`，再走现有空名 / 重名校验。这是 PRD 原文方案。
  - B. 只改后端：`LLMModelCreateReq.model_name` 用 pydantic `field_validator` `strip()`，创建 / 更新入口统一清洗。
  - C. 两端都做：页面保存前 trim，让输入框和校验跟清洗后的值一致；请求体进入 `LLMModelCreateReq` 时再 strip 一次，作为写入契约。
- **选定**：C。
- **原因**：
  - 厂商参数读的是库里的 `model_name`。只改前端，直调 `/api/v1/llm` 或旧客户端仍能写入 `" gpt-4 "`。
  - 只改后端，页面校验仍按带空格的字符串判空 / 判重：` gpt-4 ` 与 `gpt-4` 在点击保存前看起来不重名，提交后被后端合成一条或直接 10801。用户看到的值和库里的值还会差一次刷新。
  - 密钥字段已经是「前端原样 + 后端 strip」；模型名称比密钥更适合前端也 trim，因为输入框会立刻显示清洗后的值。
- **何时该重新考虑**：若模型管理改成独立微服务、写入不再经过 `LLMModelCreateReq`。

### 决策 2：后端挂在 schema，不挂 Service 循环

- **备选**：
  - A. `LLMModelCreateReq` 对 `model_name` 做 `BeforeValidator` / `field_validator`，strip 后若为空则校验失败。
  - B. 在 `LLMService.add_llm_server` / `update_llm_server` 组 `model_dict` 前手写 `one.model_name = one.model_name.strip()`。
  - C. 在 `LLMModel` ORM 的 `before_flush` 或 SQLAlchemy 事件里 strip。
- **选定**：A。
- **原因**：创建和更新共用一个请求体。挂 schema 后，路由层一进 Service 名称已经干净，`model_dict` 去重与 `server_model_uniq` 看到的是同一套值。B 要改两处且容易漏第三条写入。C 会波及内部构造 `LLMModel(...)` 的测试与回填路径，范围过大。
- **何时该重新考虑**：出现不走 `LLMModelCreateReq` 的公开写入入口。

### 决策 3：存量脏名不回填

- **备选**：
  - A. 只清洗本次写入；已入库的 `" gpt-4 "` 保持原样，管理员再保存一次即可。
  - B. `scripts/` 一次性 `UPDATE llm_model SET model_name = TRIM(model_name)`，并处理 trim 后撞唯一约束的行。
- **选定**：A。
- **原因**：PRD 是「添加时保存报错」的兼容，不是历史治理。TRIM 后撞 `server_model_uniq` 需要人工选留哪一行，不适合无人值守脚本。再保存已走决策 1 的清洗。
- **何时该重新考虑**：现场确认大量脏名导致调用持续失败，再单独立项做对账脚本。

### 决策 4：不改 19802，也不为「名称带空格」单开错误码

- **备选**：
  - A. 只消灭脏写入，错误码维持现状。
  - B. 探测厂商失败时，若 `model_name != model_name.strip()`，改返回更贴切的文案。
- **选定**：A。
- **原因**：清洗后这条路径不再被正常操作打到。19802 的语义是「目标大模型不在当前可见租户集合内」，改文案会污染真正的跨租户 / 已删除场景。厂商拒识本来就走 `ServerAddError` / 模型状态异常，不必再加码。
- **何时该重新考虑**：产品要求把「名称非法」从租户错误里拆开，且有独立文案需求。

---

## 4. 系统现状（接手必读）

### 4.1 今天（缺口）

```
管理后台 ModelConfig
  ModelItem.handleInput  → 原样写入 formData.models[].model_name
  handleSave
    → 空名 / 超长 / 重名校验（按未 trim 的字符串）
    → addLLmServer / updateLLmServer
        POST|PUT /api/v1/llm
          LLMServerCreateReq.models[].model_name   ← 无 strip
          LLMService.add_llm_server / update_llm_server
            model_dict[one.model_name] = LLMModel(...)
            落库 llm_model.model_name
          随后探测：get_bisheng_llm(model_id=...)
            params['model'] = model_info.model_name   ← 带空格发给厂商
```

对比：同一条保存链路里，`server.config` 已经走 `strip_config_whitespace`（只处理 `*_key` / `*_url` 等后缀），**模型名称不在这份名单里**。

### 4.2 改造后数据流

```
handleSave
  1. models = models.map(m => ({ ...m, model_name: m.model_name.trim() }))
  2. 回写 formData（输入框立刻显示清洗后的值）
  3. 用清洗后的名称做空名 / 超长 / 重名校验
  4. POST|PUT /api/v1/llm

LLMModelCreateReq
  field_validator("model_name") → strip()
  空串 → pydantic 校验失败（400），不进 Service

LLMService.add/update
  model_dict / 唯一约束看到的已是 strip 后的名称
  探测与后续调用的 params['model'] 不再带首尾空白
```

### 4.3 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `LLMModelCreateReq.model_name` | str，写入前 strip | 厂商模型 ID | POST/PUT `/api/v1/llm` |
| `llm_model.model_name` | VARCHAR，`(server_id, model_name)` 唯一 | 落库后的真实名称 | 实例化 `params['model']`、列表展示 |
| `ModelConfig` 条目 `model_name` | 页面输入 | 保存前 trim，与请求体对齐 | Platform 模型管理页 |

请求 / 响应 JSON 字段名不变，无新字段。

### 4.4 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `src/frontend/platform/src/pages/ModelPage/manage/ModelConfig.tsx` | `handleSave` 里统一 trim，再校验、再提交 | 不在 `onChange` 里即时 trim（输入中的空格会被吞掉，无法打字） |
| `src/backend/bisheng/llm/domain/schemas.py` | `LLMModelCreateReq.model_name` strip；空则校验失败 | 不改 `LLMServerCreateReq.name` |
| `LLMService.add_llm_server` / `update_llm_server` | 继续按 `model_name` 去重 | 不再手写第二份 strip |
| `llm/domain/llm/*.py` | 仍把库里的 `model_name` 传给厂商 | 不在调用侧再 trim（写入已干净） |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | PRD 写的报错是 19802，但 19802 的定义是「模型不在当前可见租户集合」。名称带空格的第一落点是厂商 `model` 参数对不上，保存探测失败走 `ServerAddError` / 状态异常；19802 出现在后续按 id 取模型且租户过滤看不到该行时 | 去改 19802 文案或可见性判定，真正的脏名称还在库里 | 只清洗写入；design 决策 4 |
| 2 | 前端 `handleInput` 按每次按键校验。若在 `onChange` 里 `trim()`，用户无法在名称前打空格，也没法从「空格 + 已有字」回删 | 输入体验坏掉，看起来像输入框吞字 | 只在 `handleSave` trim |
| 3 | 去空格必须发生在重名检测之前。`map[model.model_name]` 和后端 `model_dict` 用的是同一把钥匙 | `gpt-4` 与 ` gpt-4 ` 双双通过前端校验，后端 10801 或唯一约束冲突 | 前端先 trim 再 `some()`；后端 schema 先 strip 再组 dict |
| 4 | `strip_config_whitespace` 只处理配置 key 后缀，不会碰到 `models[].model_name` | 以为「保存已经去过空格」而只改前端 | 新校验器挂在 `LLMModelCreateReq`，不并进 config strip |
| 5 | 唯一约束是 `(server_id, model_name)`，不是全局模型名。跨服务商同名合法 | 误做成全局 trim 后去重 | 保持现有「同一 server 内重名」语义 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v1/llm`、`PUT /api/v1/llm` 的 `models[].model_name` 写入前 strip | 既有 HTTP 请求体语义收紧 | Platform 模型管理；其它直调客户端 |
| 落库后的 `llm_model.model_name` 不含首尾空白（新写入） | 表字段 | 所有 `get_bisheng_*` 实例化路径 |

无新 API、无新字段、无新错误码。strip 后为空走请求校验失败（400），不是业务错误码。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| 既有空名 / 超长 / 重名提示文案 | i18n `model.modelNameValidation` / `model.modelDuplicate` | 不改 key，只让校验看到 trim 后的值 |
| `server_model_uniq` | DB 唯一约束 | trim 后撞车必须在应用层先拦，避免冒出原生唯一冲突 |
| `strip_config_whitespace` | 服务商 config 清洗 | 不要把 `model_name` 塞进 config key 后缀名单 |

---

## 7. 测试与可观测

- Schema：`LLMModelCreateReq(model_name="  gpt-4  ")` → `gpt-4`；`"   "` → 校验失败。
- Service 不必为 strip 再写一条集成，组 `model_dict` 时名称已干净即可。
- 前端：`handleSave` 对 `"  gpt-4  "` 提交 `gpt-4`；只空格走空名 toast；`gpt-4` + ` gpt-4 ` 走重名 toast。
- 手动：模型管理添加服务商，名称前后加空格后保存，再进详情确认输入框与列表都是无空格名称；用该模型发一次日常对话，确认厂商侧不再因名称拒识。

---

## 8. 后续改进 / 不打算做的事

- 存量 `TRIM` 对账脚本：等现场出现批量脏名再立项。
- 输入失焦时 trim：能更早看见清洗结果，但与决策 1 的保存点重复，本期不做。
- 把 19802 拆成「名称非法」：证据不足，且会改租户错误合同。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-10 | 初版 | 将《3.0 beta2》§5.7 从「保存前 trim」一句话改成可落地的修改方案 |
