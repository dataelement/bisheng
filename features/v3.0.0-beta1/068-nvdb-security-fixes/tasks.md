# Tasks: NVDB 漏洞修复（F068）

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta2

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 用户在会话中确认修复范围与 JWT 处理口径（2026-09-14）；代码节点沙箱另议 |
| design.md | ✅ 已确认 | 同上 |
| tasks.md | ✅ 已拆解 | 3 Wave / 11 项 |
| 实现 | 🔄 进行中 | 后端代码、单测、基线回归完成（commit 16a8c6694）；e2e 复现验证与合入待做 |

---

## 开发模式

安全修复走轻量轨道：每个漏洞一组"先写会失败的测试 → 修 → 测试通过"。不建 Alembic、不加错误码、不改前端。

---

## Tasks

### Wave 1 — 后端修复（可并行）

- [x] **T001**: JWT 密钥解析模块 + 去掉代码默认值
  **文件**: `bisheng/user/domain/services/jwt_secret.py`（新）、`bisheng/core/config/settings.py`、`bisheng/common/models/config.py`、`bisheng/user/domain/services/auth.py`
  **AC**: AC-01、AC-02、AC-03、AC-05
- [x] **T002**: 排序参数白名单（接口 Literal + DAO 校验）
  **文件**: `bisheng/knowledge/domain/models/knowledge_space_file.py`、`bisheng/knowledge/api/endpoints/knowledge_space.py`
  **AC**: AC-06、AC-07、AC-08
- [x] **T003**: HTML 本地媒体目录围栏
  **文件**: `bisheng/knowledge/rag/pipeline/loader/utils/md_from_html.py`
  **AC**: AC-09、AC-10
- [x] **T004**: 文件下载工具本地路径围栏
  **文件**: `bisheng/core/cache/utils.py`
  **AC**: AC-11、AC-12
- [x] **T005**: 建应用权限依赖并挂到两个创建端点
  **文件**: `bisheng/user/domain/services/auth.py`、`bisheng/api/v1/workflow.py`、`bisheng/api/v1/assistant.py`
  **AC**: AC-13、AC-14

### Wave 2 — 测试与文档

- [x] **T006**: 五组单测（见 design §6）+ 修正 `test/tenant/test_tenant_auth.py` 合跑时的密钥来源
- [x] **T007**: `docker/bisheng/config/config.yaml` 注释示例、`docs/architecture/08-deployment.md` 配置说明与升级 checklist
- [x] **T008**: `release-contract.md` 登记 F068（表 1 无新增领域对象、INV-36、表 3、变更历史）

### Wave 3 — 验证与发版

- [x] **T009**: 基线对比回归：在改动前后的工作树对同一测试选集跑 pytest，确认无新增失败（2026-09-14：14 个目录 3900+ 用例，失败集合与基线一致；唯一差异 `test_user_string_lengths` 单次抖动、单跑通过）
- [ ] **T010**: e2e 复现验证（部署到测试机后用 NVDB 报告 PoC 逐条打）：
  - 用旧默认密钥伪造 `user_id=1` 的 cookie → 422/401，不再是超管
  - `children?order_field=if(1=1,sleep(5),1)` → 422，且响应无延迟
  - 上传含 `file:///etc/passwd` 与 `../../etc/passwd` 的 HTML → 解析成功但无对应媒体文件
  - `POST /finetune/job/file/preset {"files":"/etc/passwd"}` → 错误，对象存储无新对象
  - 关闭普通用户 `create_app` 后 `POST /workflow/create` / `POST /assistant` → 403
  - 正常路径：普通用户登录、知识空间按四种字段排序、上传普通 HTML、管理员建工作流与助手均正常
- [ ] **T011**: 发版：合入 `feat/3.0.0-beta2`，Release Notes 写入 spec §4 三条

---

## 实际偏差记录

- 无。
