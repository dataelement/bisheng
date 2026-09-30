# F070 积分系统 · UI 原型图（对照实现）

来源：`积分PRD V1.1.docx` 内嵌原型（共 **15** 张；docx 正文曾引用不存在的 `image16`，以本目录实图为准）。

**写前端时请按模块对照下表图片**，不要凭 PRD 文字自行发挥布局。

| 文件 | 端 | 模块 / 页面 | 用途 |
|------|----|-------------|------|
| [01-my-points-stats-cards.png](./01-my-points-stats-cards.png) | Portal 用户端 | 我的积分 · 统计卡片 | 余额 + 本月获得/减扣 + 排名 |
| [02-header-menu-entry.png](./02-header-menu-entry.png) | Portal 用户端 | Header 账号菜单 | 「我的积分」入口 |
| [03-my-points-page.png](./03-my-points-page.png) | Portal 用户端 | 我的积分整页 | 摘要区 + 明细表（主视觉） |
| [04-points-rules-modal.png](./04-points-rules-modal.png) | Portal 用户端 | 积分规则弹窗 | 获取/扣减规则 + 说明文案 |
| [05-home-leaderboard.png](./05-home-leaderboard.png) | Portal 用户端 | 首页积分榜 | 本月/本年/总榜 TOP10 |
| [06-admin-console-overview.png](./06-admin-console-overview.png) | Portal 管理端 | 积分管理总览 | 概览 + 规则区 + 用户区一屏 |
| [07-admin-overview-metrics.png](./07-admin-overview-metrics.png) | Portal 管理端 | 平台积分统计 | 总发放 / 余额合计 / 违规扣减 |
| [08-admin-rules-tabs.png](./08-admin-rules-tabs.png) | Portal 管理端 | 规则配置 Tab | 获取 / 扣减 / 管理员奖励 |
| [09-admin-earn-rules-list.png](./09-admin-earn-rules-list.png) | Portal 管理端 | 获取规则列表 | G1–G4 列表与启停/编辑 |
| [10-admin-earn-rule-edit.png](./10-admin-earn-rule-edit.png) | Portal 管理端 | 获取规则新增/编辑 | 分值、日上限、受益人等 |
| [11-admin-deduct-rule-edit.jpeg](./11-admin-deduct-rule-edit.jpeg) | Portal 管理端 | 扣减规则新增/编辑 | R* 表单 |
| [12-admin-reward-rule-edit.jpeg](./12-admin-reward-rule-edit.jpeg) | Portal 管理端 | 管理员奖励新增/编辑 | M* 表单 |
| [13-admin-audit-logs.png](./13-admin-audit-logs.png) | Portal 管理端 | 操作记录 | 调分/扣减审计列表 |
| [14-admin-adjust-modal.png](./14-admin-adjust-modal.png) | Portal 管理端 | 调整用户积分弹窗 | delta + 原因 |
| [15-admin-user-detail-modal.png](./15-admin-user-detail-modal.png) | Portal 管理端 | 用户积分详情弹窗 | 摘要卡 + 最近变动 |

## 同步副本

| 路径 | 说明 |
|------|------|
| `docs/PRD/积分系统/images/` | PRD 文档侧完整图（含 `raw/imageN.*` 原名） |
| `shougang-group-knowledge-portal/docs/points-ui-prototypes/` | Portal 仓前端对照副本（同文件名） |

## 实现提示

- Portal「我的积分」主视觉 → **03**（已按该图改过一轮）。
- 管理端完整运营台 → 以 **06** 为信息架构，细则弹窗对照 **10–15**。
- 权限以 design §0.1 **P1（仅平台超管）** 为准，原型若出现「公共库管理员」文案不单独扩权。
