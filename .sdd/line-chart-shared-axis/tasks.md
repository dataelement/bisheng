# 实施计划 · 折线图共用纵轴

需求 LINE-AXIS 1.0 已闭环。设计 0.1 已于 2026-11-02 确认。研发用例见 `test-cases.html`。本计划不包含浏览器验收和真实查询。

| ID | 行为 | 依据 | 依赖 | 验证 |
|---|---|---|---|---|
| T1 | 增加无界面依赖的折线图规则函数 | INV-1 至 INV-4，AD-1 | 无 | Vitest 决策表 |
| T2 | 点击和拖拽加入指标、横轴维度都调用 T1 | AC-LINE-001、003 | T1 | hook 拖拽；点击调用同一函数 |
| T3 | 改格式先判断，不合法不写入 | AC-LINE-001-06、TC-LINE-007 | T1 | 函数断言修改前后格式 |
| T4 | 两条线强制右上角图例；一条线保持原样 | AC-LINE-002 | 无 | `generateChartOption` |
| T5 | 三种语言提示原句 | 设计文案表 | T2 | 断言 zh-Hans 原句 |
| T6 | 保存配置不截断已有两个维度或异类指标 | AC-LINE-004 | T2 | hook 载入后 `getDataConfig` |

开发命令：`src/frontend/platform` 下 `npx vitest run src/test/lineChartSharedAxis.test.ts`，以及对改动文件执行 `scripts/arch-guard.sh`。

测试岗位交接：TC-QA-001、TC-QA-002。不在本计划执行。
