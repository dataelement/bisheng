# 工作台 config 修复验收记录

基线：远端 main `62f5893912a171265769f004fe79a96cfb009fee`。实现分支：`fix/workbench-config-validation`。本次未提交、未合并、未部署。用户提供的范围与验收项作为本次修复约束。

## 实现与协议

- WB-08 保留包名一致、有效 ID、恰好插入一次，允许可选 mapping config；具体允许标签、表达式和资源限额见[静态规则](workbench-package-validation.md)。
- YAML 事件扫描限制 compose 前资源，compose 后检查别名展开与所有节点；不实例化或执行 !!js。仅 config.root 的 dshHomePath 单层目录子集可通过。规范依据：[DSH 工作台开发规范](https://dshdesktop.com/workbench/docs/development/)（2026-10-27 版 §3.3）。真实宿主启动阶段才解释该标签。
- [错误契约](workbench-upload-query-design.md)保持数值 26205，追加 code/rule/field/message；前端保留 ApiError，并区分网络、超时、HTTP/413、大小、损坏和内容校验。

## 原始包验收

原包来源：[本地市场包](../../../../../../awesome-dsh-workbench/downloads/alpha3-market/packages/andoaidlaksldk__dsh-mind-workbench--1.0.15.tgz)；市场发布地址：[v1.0.15](https://github.com/andoaidlaksldk/dsh-mind-workbench/releases/download/v1.0.15/dsh-mind-workbench.tgz)。本地文件存在于相邻 awesome-dsh-workbench 仓库，未复制进本仓库、未解包落盘、未删配置或重新打包。

- 包名：dsh-mind-workbench；版本：1.0.15；大小：2,825,083 bytes。
- SHA-256：`c293cd7554c239d61d0dd1d0672c9413b9c0e5a80ddf58b473886b4ee2952d07`。
- 真实 patch 保留 `config.root: !!js dshHomePath('mind-workbench')`。
- PASS：真实 FastAPI 路由 + WorkbenchService + SQLite Repository + 内存存储适配器完成预览、导入、员工列表/详情、下载；下载字节、ETag、原文件再次读取均与原包一致。预览 allowed=true，身份 andoaidlaksldk/dsh-mind-workbench，verification_level=static。此项不覆盖真实登录/数据库/MinIO 部署环境。

复跑（在 src/backend 下；使用已安装 pytest 的 Python）：

```bash
WORKBENCH_ORIGINAL_TGZ=/absolute/path/to/andoaidlaksldk__dsh-mind-workbench--1.0.15.tgz python -m pytest test/dsh_market/test_workbench.py -q
```

原包测试是显式 opt-in；未设置环境变量时只跳过这一项，CI 不依赖开发者本地目录。该测试固定原包 SHA，防止误用删配置后的包。

## 自动验证

| 检查 | 结果与范围 |
| --- | --- |
| 工作台回归 | 38 项通过（包含原包；整个市场套件中执行），覆盖旧 name/id、config、包名错、缺 ID、空白 ID、额外字段、非 mapping、未知表达式/标签、路径逃逸/追加表达式、循环/展开别名、重复键、深度/节点限额、ID 插入数及 API 明细。另有构造器陷阱测试，证明合法 !!js 未触发 YAML 对象构造。 |
| 市场模块（原包环境变量已设置） | 94 passed / 1 failed，新增 23 个通过；无跳过。唯一失败为本地 MCP SDK 不接受 max_request_body_size，在导入 bisheng.main 时触发。 |
| 干净 main 对照 | 同一 Python/同一 test/dsh_market 选择：71 passed / 1 failed；同一个 MCP 构造参数错误。无新增失败。 |
| Ruff | 修改的四个后端文件 check/format 通过（包括 F821）；修复独立审查发现的 I001 导入排序。 |
| 前端 | 4 文件共 40 项通过：错误 presenter/请求集成 14、上传对话框集成 5、既有请求错误契约 6、既有市场页面 15；全前端 lint、typecheck、check-i18n、locales:check 通过。 |
| 架构与 diff | 修改代码逐文件运行 arch-guard 无输出；git diff --check 通过。 |

后端使用现有 Python 3.12 虚拟环境与无中间件测试；最小本地 config.yaml 仅为测试启动创建，未纳入交付。尚未在项目指定的 Python 3.11 或部署中间件环境复核。

独立 sdd-code-review 最终复核 PASS，七个维度均无 HIGH/MEDIUM 遗留；初审发现的规则文档冲突及测试导入排序已修正。审查范围为后端实现、错误适配、测试与文档；不认证尚未执行的 alpha3/真实中间件验收。

## 剩余 alpha3 运行验收

状态：NOT_RUN，不能确认 alpha3 版本适配。已识别本机 DSH Desktop 0.13.2 内 Harness/client 0.2.2-alpha.2，BISHENG 1.2.0 内 0.2.1-rc.2；均不是已确认的目标 alpha3。已向用户请求目标 alpha3 应用/源码路径或连接信息；未把无回答视为认可替代版本。

补充只读核查：相邻 dsh-desktop 源码 package.json 声明 @deepseek-ai/dsh 0.2.2-alpha.2；另一个已安装 DeepSeek Harness 应用 CFBundleShortVersionString 为 0.2.1-rc.3；相邻 dsh-market-exact-compatible-install 是市场插件源码，不是 alpha3 宿主。尚未找到已确认的目标 alpha3 应用及其配置 profile，安装运行验收因此等待目标环境信息。

有目标环境后，逐项记录宿主精确版本、配置 profile、原包 SHA 和日志：

- [ ] 在目标 alpha3 上原样安装上述 TGZ，确认依赖解析及 Harness 加载。
- [ ] 启动后确认 config.root 落在目标宿主 dshHomePath 对应目录，无表达式解析错误。
- [ ] 打开工作台，新建、编辑、保存思维导图；执行包提供的导出操作。
- [ ] 重启目标宿主，再打开并读取已保存内容，确认注册、持久化和 UI 正常。
- [ ] 以真实管理员浏览器上传原包，核对页面预览；上传拒绝包、模拟网络失败，确认原因可读且不可提交。
- [ ] 在真实服务环境验证 MySQL/DM8、MinIO 与登录权限；本地组件/ASGI 测试不能代替这些项。
