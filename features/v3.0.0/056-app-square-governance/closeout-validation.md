# 收尾定向验证与 L1：056-app-square-governance

日期：2026-10-24。用户已单独确认修订设计。实现基线 `818a12968`，当前源码/命令证据见 [JSON](./closeout-validation.json)；本轮提交号以 Git 记录和统一提测报告为准。

## 状态

本轮主功能编码已接齐，按用户要求进行定向验证。**真实部署 E2E、最终 L2 和合入仍未完成，不是全部交付 PASS。** 未运行全量测试，跨命令用例有重叠，不将计数直接相加。

## 已执行的主要检查

| 范围 | 结果 / 证据 |
|---|---|
| 后端三源查询、导出、凭据审计、报告等收尾批 | 30 passed；JSON 记录实际路径，后续修复只重跑对应路径 |
| OBO 正式与预览，存在性/权限顺序、配置快照、无效 key、正常签发 | 48 passed |
| app-proxy 三语页面/正式和预览旧 allow 不复用 | 5 passed；纯渲染/MockTransport，不使用主机网络 |
| app-proxy 规范 HTTP 入口授权缓存回归 | 4 passed；loopback fake upstream，不是真实部署；规范入口每请求一次判定 |
| manager 自有规则/适配器门禁/legacy 状态读面 | 9 passed；真实防火墙命令未执行 |
| 宿主报告、心跳不能续证明及导出租约交接补测 | 5 passed |
| 下载完整字节数与 immutable CSV | 1 passed |
| 审计页原两页签、门禁、记录展示与分页作用域 | 两文件 9 passed；候选分页更新后只重跑对应组件 4 passed |
| 真实环境 E2E 用例 | 4 条 collected，未运行；不能记为通过 |
| 静态检查 | 改动 Python Ruff、逐文件架构守卫无 VIOLATION、单 Alembic head、Compose YAML/独立角色配置、安装脚本 bash 语法、运行记录三语 keys 对齐 |
| 前端类型检查 | 本次文件无新增错误；仍有两条既有阻塞：OrgKbConfig 缺 @hello-pangea/dnd 类型声明，clientVoiceDraft.test 参数签名；其文件未被本轮改动 |

## Task Review（L1，按 tasks.md 本轮实现/测试任务）

| # | 检查 | 结果 | 依据 |
|---|---|---|---|
| 1 | 分层 | PASS | Endpoint → Service → Repository；backend 无 Engine/防火墙调用；跨域通过公开应用协议 |
| 2 | 命名 / 路径 | PASS | 测试位于模块目录；LogPage 命名导出，惰性路由已接；不新增含 config 的公共 URL |
| 3 | 序列化 | PASS | 白名单元数据，无完整 ORM/任意 metadata 透传；内部 HMAC 报告独立合同 |
| 4 | 数据库 | PASS（静态/SQLite） | JsonType/通用字段、请求者 tenant 默认 None + NOT NULL；批量删除带显式 tenant；节点报告为已批准的全局事实；DM8 未真实执行 |
| 5 | 前端 | PASS_WITH_NOTES | 复用 UI 与 request/query；三语同提交；已收缩旧 Hook ESLint suppression；两条既有类型错误未扩大范围修复 |
| 6 | 信息泄漏 | PASS | OBO/业务值不进入查询/导出；凭据仅 mask；无公开 MinIO URL；CSV 公式防护；源码无真实密钥 |
| 7 | 设计同步 | PASS | 正式设计补记实现合同、源时区、取消/GC、宿主安装位置与实际门禁；批准时 hash 保留在任务记录 |

元数据：实际新增入口/配置/夹具已补回 tasks.md；配对测试按上述真实结果登记。**阶段结果 PASS_WITH_NOTES；不替代最终 `/sdd-code-review`。**

## 提测与暂缓事项

统一见 [提测报告](../../../docs/reviews/vibe-governance-closeout-handoff-2026-10-24.md)。优先验证 Docker 109 与 K8s 189 的保存不重启、确认后重建、三源查询/导出与权限；Docker 再验证真实宿主 INPUT/FORWARD、iptables/nftables 与证明过期。

按用户边界，超长暂停旧 worker 与 GC 晚到上传、跨节点时钟偏差、历史混合/DST 时区等低概率组合列待验，不继续扩展状态机。本轮没有公开推送、tag 或镜像发行。
