# Tasks: 深度研究 PPT 制作改用 PPTD 页面设计引擎

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.1.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-11 用户确认（同名原地替换方案） |
| design.md | ✅ 已评审 | 2026-11-11 用户确认 |
| tasks.md | ✅ 已拆解 | 2026-11-11 |
| 实现 | 🔄 进行中 | 7 / 9（T08/T09 环境验收待做；T02 应用镜像 FROM 切 base.v11 待 base 发布） |

---

## Tasks

### Wave 1（互不依赖，可并行）

- [x] **T01**：引擎副本与依赖清单
  **文件**：`src/backend/pptd_runtime/{dsh-ppt/,package.json,package-lock.json,README.md,install.sh}`
  **逻辑**：从 dsh-desktop `46666d3` 拷 `packages/ppt-runtime/core` 的 `lib/ LICENSE THIRD_PARTY_NOTICES.md licenses/`；package.json 只列 6 个依赖（精确版本）；`install.sh` 下载 Node 官方二进制到 `/opt/pptd-runtime/bin`、`npm ci`、拷库、`chmod -R a+rX`，幂等。设计见 design 决策 2–4。
  **覆盖 AC**：AC-01、AC-03、AC-04

- [x] **T02**：镜像
  **文件**：`src/backend/base.Dockerfile`、`src/backend/Dockerfile`
  **逻辑**：base 按 `TARGETARCH` 装 Node 与 `npm ci`；应用镜像 `COPY pptd_runtime/dsh-ppt /opt/pptd-runtime/dsh-ppt`。应用镜像的 `FROM` 在 base.v11 发布后再切换（发布需用户确认）。
  **覆盖 AC**：AC-01

- [x] **T03**：技能包正文与脚本替换
  **文件**：`builtin_skills/bisheng-pptx/{SKILL.md,references/,scripts/pptd.py}`；删除旧 scripts/templates/references 与 `src/backend/scripts/pptx_templates/`
  **逻辑**：design 决策 5；`pptd.py` 增加 `convert`。
  **覆盖 AC**：AC-04～AC-10、AC-15、AC-16

- [x] **T04**：16 套模板去品牌迁入
  **文件**：`builtin_skills/bisheng-pptx/templates/<id>/{design.md,source-zh/}`、`templates/catalog.md`
  **覆盖 AC**：AC-12、AC-13

- [x] **T05**：版本契约与编写规则
  **文件**：`features/v3.1.0-beta1/release-contract.md`、`builtin_skills/AGENTS.md`（旧脚本示例改指 `pptd.py`）、F006 spec 注记
  **覆盖 AC**：AC-20（文档侧）

### Wave 2

- [x] **T06**：政企红色模板（依赖 T01、T04）
  **文件**：`builtin_skills/bisheng-pptx/templates/gov-red/`
  **逻辑**：design 决策 6；12 个参考页均通过引擎检查与字号下限。
  **覆盖 AC**：AC-12、AC-14

- [x] **T07**：测试（依赖 T03、T04、T06）
  **文件**：`test/linsight/test_pptx_pptd_skill.py`（新）、`test_html_slides.py`、`test_builtin_skill_scripts.py`、`test_builtin_skill_seeder.py`、`test_pptx_templates.py`（删）、`test/dsh/test_skill_display_locale.py`
  **逻辑**：design §7 列出的静态测试与引擎集成测试；旧技能脚本测试删除。
  **覆盖 AC**：AC-09、AC-10、AC-13、AC-17、AC-18、AC-20

### Wave 3

- [ ] **T08**：114 验收（依赖全部）
  **逻辑**：部署分支、跑 `install.sh`、确认种子替换（AC-17）、重跑 4 题出三方对比。
  **覆盖 AC**：AC-02、AC-11、AC-14、AC-17、AC-19、AC-21

- [ ] **T09**：arm64 验收（依赖 T08）
  **逻辑**：106.63.13.186 是中债测试环境（客户环境），不在上面安装。改为在 base.v11 的 arm64 原生构建（`base_ci.yml`，`ubuntu-22.04-arm`）中加载 sharp 原生库，加载失败即构建失败；发布 base.v11 前须用户确认。
  **覆盖 AC**：AC-22

## 实际偏差记录

- T01：运行时引擎目录由 `dsh-ppt` 改为 `engine`（去品牌）→ design 决策 2/3。
- T06：政企红模板改为生成脚本 → design 决策 6。
- T08：114 上发现 PyYAML 缺失时字号检查被当成问题而阻断导出，改为跳过并提示（生产 venv 有 PyYAML，不受影响）；补测试。
- T09：ARM 验收改为 base 镜像 arm64 构建期检查 → 见 T09。
- T07：`test_builtin_skill_scripts.py` 删除旧 pptx 检查脚本用例；`test_pptx_templates.py` 删除；新增 `test_pptx_pptd_skill.py`（16 项，3 项需要引擎）。
