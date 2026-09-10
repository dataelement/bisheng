# Tasks: 模型名称首尾空格兼容

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认 |
| design.md | ✅ 已评审 | 用户确认；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 3 Wave / 4 项 |
| 实现 | ✅ 已完成 | 4 / 4 完成 |

---

## 开发模式

按 Wave 组织。后端 schema 先写测试再改实现。前端抽出纯函数，用 vitest 覆盖 trim / 空名 / 重名。

---

## Tasks

### Wave 1 — 后端写入契约

- [x] **T001**: `LLMModelCreateReq.model_name` strip 测试
  **文件**: `src/backend/test/llm/test_llm_model_name_strip.py`
  **逻辑**: 首尾空格 / 制表符 / 换行被去掉；中间空格保留；只空白校验失败；经 `LLMServerCreateReq` 嵌套同样生效
  **覆盖 AC**: AC-01, AC-03, AC-05
  **依赖**: 无

- [x] **T002**: schema 校验器
  **文件**: `src/backend/bisheng/llm/domain/schemas.py`
  **逻辑**: `model_name` `before` validator `strip()`；strip 后空串走 pydantic 校验失败，不进 Service。不改服务商名、不并进 `strip_config_whitespace`
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-06
  **依赖**: T001

### Wave 2 — Platform 保存

- [x] **T003**: 保存前 trim 再校验再提交
  **文件**: `src/frontend/platform/src/pages/ModelPage/manage/modelNameTrim.ts`,
           `src/frontend/platform/src/pages/ModelPage/manage/ModelConfig.tsx`
  **逻辑**: `handleSave` 用 `trimModelNames` 清洗全部条目，回写 formData，再空名 / 超长 / 重名校验，提交清洗后的 `models`。不在 `onChange` 里 trim
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-06
  **依赖**: T002

### Wave 3 — 前端测试

- [x] **T004**: trim 与保存前校验测试
  **文件**: `src/frontend/platform/src/test/f065ModelNameTrim.test.ts`
  **逻辑**: `"  gpt-4  "` → `gpt-4`；只空格 → 空串；`gpt-4` + `" gpt-4 "` 清洗后重名
  **覆盖 AC**: AC-01, AC-03, AC-04
  **依赖**: T003

---

## 实际偏差记录

（实现中如有偏离，只留一行指针，论证回写 design.md。）

- T002：空名是 pydantic 校验失败，HTTP 状态为框架默认 422，未改成 400。见 design.md §4.2 / §6.1。
