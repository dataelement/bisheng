# 授权对象搜索空态文案 — 2026-10-30

- 目标：`dataelement/bisheng:feat/bisheng-work-120-main`，基线 `06ffc6fba6543e774676f8a1f45838c29e97a327`；分支 `codex/permission-search-empty`。
- 根因：部门、用户组和已授权列表的搜索空态共同使用用户专属文案键。部门与用户组现在分别显示“暂无匹配部门”“暂无匹配用户组”；已授权列表按当前对象类型选择文案。中英日同步，空数据提示和搜索接口沿用现有逻辑。
- 新增 9 项组件行为回归，覆盖中英日部门/用户组搜索、清空搜索恢复，以及三种授权对象的列表空态。相关 14 项通过；目标基线运行相同回归时 8 项失败、6 项通过。
- 权限模块整体：57 项通过、2 项失败。这两项在目标基线同样失败：`PermissionDraftPickerDialog.test.tsx` 仍断言旧 Tabs 结构；`permissionI18n.test.ts` 将未改动的 `SourceBadge.tsx` 中文注释识别为硬编码文案。原文件保留，范围明确记录。
- 前端 workspace 完整 lint/typecheck、Client 生产构建、三语言 key 检查、架构守卫与差异检查通过。验证复用锁文件一致的本地依赖，使用项目指定 pnpm 9.15.9。
- 按仓库 code-review 七维检查完成，代码变更集中在空态文案选择和对应翻译；边界、权限、并发、信息、覆盖、风格与文档检查均未发现本次新增问题。
- 本地证据：总工作区 `outputs/permission-search-empty-20261030/`。部署、Windows 安装版及真实账号验收待执行。
