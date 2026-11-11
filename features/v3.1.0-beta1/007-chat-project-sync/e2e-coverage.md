# E2E Coverage：项目三端同步

范围：真实 ASGI/Service/SQLite + Web 行为测试 + 真实 Electron/双 HTTP fixture + 3006 初步联合观察。认证、数据库与传输替身的边界见 verification.md。

| AC | 覆盖与实际结果 | 剩余环境验证 |
| --- | --- | --- |
| 01 | projects_repository / projects_api / e2e：双客户端读回；3006 Web 项目在 Desktop 出现 | 正式安装包 |
| 02 | projects_events ACK/心跳、Web stream、main controller；Electron 25 ms 自动更新 | 实际 Gateway 时延与多节点 |
| 03 | project_session_lifecycle 原子绑定/重放、两个真实初始化入口；Web 普通/任务意图与导航用例 | 真实模型普通/任务完整首轮 |
| 04 | 独立历史 125 项、快照 501 项、native old history、默认列表过滤 | 全部真实历史搜索矩阵 |
| 05 | 原子 unlink、项目删除保留 chat、chat 删除无 ghost；native 删除重试 | 目标环境清理矩阵 |
| 06 | 单操作 SQL/唯一键、快照 cursor 失效、高水位及迟到响应测试 | MySQL 真实并发压力 |
| 07 | 幂等回执、响应丢失、自动重连、心跳补漏；native reconnect | OS 真实休眠 |
| 08 | 错误 envelope、保稿同 UUID、同步状态；真实页面失败保稿后重试成功 | Gateway 故障注入 |
| 09 | main epoch/dispose/auth renewal，Web 中断批次和来源绑定 | 真实多个账号/租户切换 |
| 10 | ordinary/foreign/tenant/admin 合成 actor 在真实 SQL/ASGI 全部拒绝越界 | 专用非管理员真实登录 |
| 11 | server 幂等导入/云端优先/删除不复活、Web/desktop 自动批次与重试 | 旧版真实账号全量核对 |
| 12 | Web 第一次自动迁移绑定来源，换账号不接管；无手动入口 | 历史无账号记录的现场抽样 |
| 13 | Sidebar 中英/明暗、移动端、native dialogs，Work 保留本地边界 | Windows 与正式包 |

整体状态：PARTIAL（源码与隔离运行通过；目标平台矩阵未全部执行）。不把每条 AC 的自动化映射视为所有部署条件均已验收。
