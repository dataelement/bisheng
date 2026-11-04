# 返回应用广场热修

## 根因和目标

用户访问 `/apps/today-tasks-demo` 的停用提示页，点击“返回广场”进入404。代码与116实际配置均未指定 `APP_PROXY_SQUARE_URL`，默认 `/workspace`。116的nginx仅以 `/workspace/` 分流client；裸路径进入platform SPA。正确目标是client应用广场 `/workspace/apps/explore`（`ExplorePlaza`），不是需要构建权限的后台页面。

源码修复：`app_proxy.config.DEFAULT_SQUARE_URL` 指向完整广场路由，页面渲染器共用此默认值，保留环境变量覆盖。116以Compose环境变量显式配置正确目标，保留原镜像，仅重建app-proxy；隔离绑定IP不变，未修改应用或审批状态。配置原件已在116 root-only目录备份。

## 定向验证与审查

| 维度 | 结果 |
|---|---|
| 边界 | 默认、空环境变量及自定义部署前缀；停用/拒绝/不存在页面均指向client路由 |
| 认证 | 既有认证和权限判断不变；真实验证使用已授权专用测试账号正常登录，会话仅在内存 |
| 并发 | 仅默认路径/配置修改，不增加缓存或状态 |
| 信息泄漏 | 不新增用户、凭据、日志或跨应用读取 |
| 测试 | `tests/test_square_target.py` 8 passed；未跑全量。既有WebSocket fixture需要本机回环监听，因此在沙箱外执行 |
| 风格 | Ruff、架构守卫、diff检查通过 |
| 文档 | F054设计及任务追加记录同步 |

结论：热修代码自审 PASS。本记录与源码修复一起交付，提交及远端SHA以Git核验结果为准。

116真实登录只读验证：`/apps/today-tasks-demo` 提示页HTTP200，实际按钮href为 `/workspace/apps/explore`；目标HTTP200且加载client SPA。未执行浏览器视觉点击验收，HTTP200本身不等于完整浏览器功能验收。用户刷新停用提示页后即可获取新href。
