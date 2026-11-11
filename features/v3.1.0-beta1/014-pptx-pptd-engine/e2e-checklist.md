# E2E 覆盖: F014 PPT 制作改用 PPTD 引擎

**运行时间**: 2026-11-11 台北时间晚间
**环境**: 192.168.106.114（x86），后端为本分支的 `bisheng-pptx` 技能包与 `pptd_runtime`（rsync 部署，内容哈希 `b8b646de…` 与分支一致），引擎由 `install.sh` 安装在 `/opt/pptd-runtime`
**测试文件**: `src/backend/test/e2e/test_e2e_f014_pptx_pptd_engine.py`（只读，不建数据）

```bash
E2E_API_BASE=http://<host>:7860/api/v1 E2E_ADMIN_TOKEN=... \
E2E_USER_NAME=... E2E_USER_PASSWORD=... \
pytest test/e2e/test_e2e_f014_pptx_pptd_engine.py
```

引擎相关的一项需要运行 pytest 的机器装有引擎，所以在部署机上运行；普通用户配对项需要普通用户账号，缺省时跳过。

## API 与技能包（自动化，8 / 8 通过）

| AC | 内容 | 状态 | 测试方法 |
|---|---|---|---|
| AC-05 | 显示名「PPT 制作」；两个技能的描述互相写明 .pptx / 网页分界 | ✅ | `test_ac05_trigger_boundary_with_html_report` |
| AC-17 | 内置行原地替换：来源仍为 builtin、启用状态保留、内容哈希等于本分支 | ✅ | `test_ac17_upgrade_replaced_builtin_in_place` |
| AC-17 拒绝 | 普通用户读管理详情答 19801；普通用户的运行时目录里只有一个 `bisheng-pptx` | ✅ | `test_ac17_denied_for_plain_user` |
| AC-19 | 运行时目录只有一个制作 .pptx 的技能，验证期的 `pptd-deck` 不存在（11053） | ✅ | `test_ac19_only_one_pptx_skill_mounted` |
| AC-19 拒绝 | 用旧内容哈希下载技能包答 11051 | ✅ | `test_bundle_rejects_stale_version` |
| AC-12 / AC-13 | 下发的包：17 套模板各 12 页、政企红在目录首行、旧脚本与 .pptx 模板已删、客户可读文件无品牌名 | ✅ | `test_ac12_ac13_bundle_contents` |
| AC-04 | 下发的脚本在没有引擎时提示联系管理员并给出「需要修改」 | ✅ | `test_ac04_missing_engine_stops_with_notice` |
| AC-01 / 02 / 09 / 10 | 用下发的包检查并导出政企红：12 页、无媒体文件、字体只有 YaHei 与 Arial；字号改到 8pt 后拒绝导出 | ✅ | `test_ac01_ac09_ac10_engine_check_and_render` |

AC-18（租户改过的版本不被覆盖）需要改动内置行，E2E 不做，由 `test/linsight/test_builtin_skill_seeder.py` 覆盖。AC-20 由 `test/linsight/test_html_slides.py` 覆盖。

## 模型行为（114 实跑，见 design §7）

| AC | 证据 |
|---|---|
| AC-06 / 07 / 08 / 11 / 14 / 21 | 2026-11-11 题集 4 题各跑一次（DeepSeek-V4.1-Flash）：273–499 秒，均先检查通过再导出；字号中位数 11–14pt，小于 10pt 的占比 ≤18%；P1 选用政企红 |
| AC-01（container 模式） | 沙箱镜像构建阶段 + `ContainerExecutor` 在 uid 10000、只读根文件系统下完成 env/check/render，6.4 秒 |

## 仍需人工完成

- [ ] **AC-15 / AC-16**：在深度研究里上传一份 .pptx，分别要求「翻新这份 PPT」和「按这个模板做一版」。预期：先转换成工程再修改；交付说明列出被简化的效果，并写明导出文件不带原母版。转换本身已由单元测试的往返测试覆盖，这一项只验证模型是否按技能步骤操作。
- [ ] **AC-22**：base.v11 的 arm64 构建已通过（2026-11-12，构建内 sharp 加载检查打印 `sharp 0.35.5 arm64`）；剩余：在 arm64 环境用新应用镜像跑 1 道题。
- [ ] **回归**：深度研究技能选择列表里「PPT 制作」「网页报告」正常显示，勾选状态与升级前一致。

## 整体状态: PASS（自动化部分）；AC-15/16/22 待人工
