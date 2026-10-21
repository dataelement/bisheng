# F086 部署验收清单

**状态：Docker主链路与双架构原生容器验证通过，完整验收仍有缺口。** [真实记录](./live-validation.md)与日志已归档。复合场景只完成部分断言时保留未勾选，并在下表记录差额；不将skip计为通过。K8s执行器归F059。

## 自动化入口与证据边界

| 入口 | 实际覆盖 | 不覆盖 |
| --- | --- | --- |
| `test/app_runtime/test_runtime_*`、`test/app_publish/test_*delivery*` | 真 SQL SQLite 事务、业务服务、ASGI、清单、权限 guard、HMAC、完整性、阶段/路由/凭据控制；外部端口替换 | MySQL/DM8 真并发、Engine、平台全链路 |
| `src/runtime-manager/tests` | 准备/复用/归属/恢复、SQLite、传输、出站和启动合同；多数 Engine 为端口替换 | 真实容器安装依赖和双架构效果 |
| `scripts/smoke_runtime_delivery.py` | 已在两种原生Engine执行：禁网Python/Node/static、代码复用、SQLite helper/备份、Node钩子/前端构建、本地CPython C扩展；内存产物端口 | backend、MinIO、Redis、OpenFGA、审批和用户鉴权 |
| `test/e2e/test_e2e_f086_runtime_delivery.py` | 专用部署上 owner/nonowner/跨租户快照与恢复拒绝、目录读取/default CAS权限 | 本文件不会代替人审批，也不创建或删除应用；发布/故障旅程见下表 |

E2E 只在显式 `F086_E2E=1` 时运行。必填环境：`E2E_API_BASE`，`F086_E2E_APP_ID`、`F086_E2E_TENANT_ID`，以及 `F086_E2E_OWNER_USERNAME/PASSWORD`、`F086_E2E_NONOWNER_USERNAME/PASSWORD`、`F086_E2E_FOREIGN_USERNAME/PASSWORD`。使用预先创建、名为 `e2e-f086-*` 的专用应用和两个不同租户的普通账号；owner 不得为超管。密码通过安全环境注入，不写测试或报告。

该自动化测试不创建平台资源，因此无删除 cleanup；下面的可写旅程只允许处理套件本次创建、已登记 ID 且名称以 `e2e-f086-` 开头的资源。执行前清理本套件残留，结束后按同一前缀和 ID 清理；禁止整库、整桶或 Docker prune。

```bash
cd src/backend
PYTHONPATH=. uv run pytest test/e2e/test_e2e_f086_runtime_delivery.py -v
```

未设置开关时的 **6 skipped 仅证明安全门有效，不是 E2E 通过**。

## 必须留证的旅程

| 完成 | 场景与断言 | AC |
| --- | --- | --- |
| [ ] | CLI 上传 v2 原包 → backend 快照 → Celery 扫描/结构预检 → manager prepare/probe → 原审批入口 → 人批准 → ready/业务事务提交 → 浏览器 HTTP/WS。保存 deployment/version/op/route/asset 关联 | AC-01、AC-03、AC-06、AC-11、AC-17、AC-33、AC-48 |
| [ ] | 只改业务代码二次发布；Engine 无 build/push，dependency artifact/environment key 相同，运行代码变化。依赖、ABI或源码安装钩子输入变化后不得误复用 | AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25 |
| [ ] | v1 项目在协议2通过显式旧模板构建；完整 image 不安装 pip/npm；坏入口/错端口/错架构在审批前失败，不生成上线记录 | AC-12、AC-13、AC-16、AC-17、AC-18、AC-60 |
| [ ] | 无外网/无仓库：save/load精确镜像及目录、基础补包后首次发布成功。新增未供应依赖必须失败且无公共 fallback；owner 补包后成功。篡改hash/错ABI/跨app私包引用拒绝 | AC-07、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-55、AC-59 |
| [ ] | 超管登记新 profile 修订和 CAS 默认；历史运行/审批版本组合不变；普通owner、租管、SAK不能全局写。SAK可发布普通更新、消费owner已绑定材料但不能自行管理私包 | AC-14、AC-15、AC-30、AC-56 |
| [ ] | SQLite 存数据；停用/恢复/代码升级后保留；预览数据库和附件写入不能进入生产。停用释放执行资源，删除按原owner动作清理明确资产 | AC-08、AC-09、AC-10、AC-38、AC-39、AC-41 |
| [ ] | DDL 前停写、同一Backup API一致快照；模拟 MinIO PUT成功但SQL finalize失败，断言没有DDL。DDL提交后启动失败显示维护/数据可能改变；不自动覆盖DB | AC-37、AC-42、AC-43、AC-44 |
| [ ] | owner 明确确认恢复某 snapshot；先保护当前库、同卷rename/WAL处理；停用应用保持停用，在线应用重探活。非owner超管、租管、SAK、跨租户均拒绝；审计有app/actor/op | AC-30、AC-45、AC-46、AC-47、AC-53 |
| [ ] | SDK0.1.1实际经backend附件上传/列表/下载/删除、20MiB边界、撤销；模型接口和检索执行声明∩当前访客权限；预览仍按F055 owner例外计审计 | AC-05、AC-07、AC-51、AC-53、AC-59 |
| [ ] | manager停止超过3秒，入口持续HTTP/WS、egress现有连接仍以backend读模型授权；平台权限/策略失联后硬期限拒绝并关闭CONNECT/WS。两种故障分别测试 | AC-48、AC-49、AC-50、AC-51、AC-52 |
| [ ] | 竞争最后容量、多worker相同幂等键/丢ACK、重启重复fact；只有一份当前归属及一个正式SQLite写入者。旧Engine不可确定停止时不接管/不释放；不依赖本地JSON权威 | AC-34、AC-35、AC-36、AC-37、AC-40、AC-61 |
| [ ] | 每阶段异常/超时/取消/杀manager后15分钟回收界内对账标签容器、scratch和reservation；未停确认仍占资源；保护生产库、引用产物和唯一未确认备份 | AC-26、AC-63 |
| [ ] | amd64及arm64原生执行Python原生wheel、Node安装脚本/前端编译、static、实际非root挂载/数据helper/断网恢复。CI双平台成功才提供官方目录 | AC-02、AC-04、AC-31、AC-54、AC-55、AC-56、AC-57、AC-58 |
| [ ] | 旧平台 inventory dry-run/hash确认/维护导入/重绑定；原版本及存储对象hash不改，旧桶差异明确拒绝。配置安装手册和系统回退演练 | AC-03、AC-08、AC-10、AC-13、AC-46、AC-57、AC-60、AC-62 |

## 证据格式

记录 commit/镜像配置ID与digest、节点平台/Engine ID、脱敏配置摘要、请求时间、实际状态转换、容器/挂载/网络事实、数据与对象哈希、失败阶段、清理确认及原资源未变化的证据。不得记录 HMAC、Cookie、OBO、应用token、包源账号或下载票据。

MySQL已执行5项同步竞争与事务测试；DM8待专用环境。SQLite合同与MySQL证明均不能替代DM8的驱动、DDL、唯一约束和savepoint验收。

## 本轮已取得证据与仍缺断言

| 旅程 | 已验证 | 仍缺 |
| --- | --- | --- |
| CLI与审批上线 | 实际wheel/SAK→源码→Celery→预检→审批→上线，HTTP/WS/SDK | 全部阶段中断/取消矩阵 |
| 复用与编译 | v1→v2产物复用；两架构五场景，C扩展/Node钩子源码变化失效 | 平台全链路的全部ABI错误组合 |
| 完整镜像/v1兼容 | 实际预检、审批、上线、HTTP200、owner清理；错误端口审批前拒绝且无正式版本 | 错架构/坏入口的全部平台组合 |
| 离线 | 基础镜像转存、禁网准备、缺包失败、owner导入、CLI自动重试 | 完整客户平台断网新装 |
| SQLite与数据 | 预览库隔离、DDL前快照、owner恢复、停用保持、保护快照、正式删除清理 | 上传成功但SQL确认失败注入、DDL后启动失败及每种拒绝主体 |
| 入口与故障 | manager停止仍HTTP/SDK可用；backend停止503 | 已建立WS/CONNECT撤权硬期限、全部模型/检索场景 |
| 并发 | MySQL强制12路幂等、2路归属竞争、容量/回滚/范围拒绝 | DM8、旧Engine失联与全部多进程恢复 |
| 原生发行 | amd64/arm64七镜像原生构建、每侧五场景 | GitHub工作流与正式索引/目录发布 |
| 维护升级 | 本地合同测试 | 存量平台真实inventory/import/回退 |
