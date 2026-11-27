"""Standalone reports from the analyzed result, without business recalculation."""
import html
import json
import math
from pathlib import Path

DASH = "—"
STATUS = {"predicted": "可预测", "mixed": "部分可预测", "unpredictable": "不可预测",
          "no_history": "无匹配历史", "needs_input": "待补充输入",
          "api_error": "预测服务异常", "history_error": "历史服务异常"}


def display(value):
    if value is None or value == "":
        return DASH
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def esc(value):
    return html.escape(display(value), quote=True)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return DASH
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def md(value):
    """Escape data as Markdown text, including raw HTML and table delimiters."""
    value = html.escape(display(value), quote=True).replace("\r\n", "\n").replace("\r", "\n")
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#", "~", "!", "(", ")", "{", "}"):
        value = value.replace(char, "\\" + char)
    return value.replace("\n", "<br>")


def refs(value):
    if isinstance(value, list):
        return "、".join(display(x) for x in value) or DASH
    return display(value)


def _document(result):
    """Both export formats consume exactly these presentation-only blocks."""
    blocks = []
    h = result.get("history") or {}
    f = result.get("forecast") or {}
    e = result.get("explanation") or {}
    d = result.get("report_dimensions") or {}
    a = result.get("analytics") or {}
    p = result.get("provenance") or {}
    batch = result.get("batch") or {}
    period = result.get("period") or {}
    items = result.get("items") or []
    unit, currency = display(result.get("unit")), display(result.get("currency"))

    def heading(title, accent="blue"):
        blocks.append(("heading", title, accent))

    def paragraph(text, kind="body"):
        if text is not None and text != "":
            blocks.append(("paragraph", text, kind))

    def table(headers, rows):
        blocks.append(("table", headers, rows))

    def values(rows):
        table(["项目", "本次结果"], rows)

    heading("分析范围与运行参数")
    values([
        ["规格 / 物料", f"{display(result.get('spec'))} / {display(result.get('material'))}"],
        ["客户", "全部客户" if result.get("customer")=="all" else result.get("customer")], ["状态", STATUS.get(result.get("status"), result.get("status"))],
        ["所选周期", period.get("label")],
        ["预测区间", f"{display(period.get('start'))} 至 {display(period.get('end'))}"],
        ["起始月 / 月数", f"{display(period.get('start_month'))} / {display(period.get('months'))}"],
        ["时间粒度", "月度" if period.get("key")=="monthly" else period.get("key")], ["单位 / 币种", f"{unit} / {currency}"],
        ["生成时间", result.get("generated_at")], ["查询编号", result.get("request_id")],
    ])
    heading("分析结论")
    paragraph(result.get("message"), "note")
    paragraph(e.get("headline"), "lead")
    paragraph(e.get("body"))
    paragraph("测试数据与模拟预测 API 用于流程验证。解释由平台 Agent 基于本次工具事实生成；历史查询适配方式以来源记录为准，专用 NL2SQL 尚待接入，不代表实际采购需求或模型效果。", "warning")
    excluded = d.get("excluded_specs") or []
    if result.get("status") == "mixed" or excluded:
        paragraph("汇总口径：以下预测小计和合同建议只覆盖可预测部分。不可预测物料未计入预测小计，不按 0 处理；完整范围见物料维度与状态表。", "warning")
    paragraph("合计由服务逐月预测汇总。历史与预测分别列示；缺失数量、单价和金额显示为 —，不回填为零。", "note")
    summary = f.get("summary") or {}
    values([["预测数量小计", number(summary.get("quantity"))],
            ["预测金额小计", number(summary.get("amount"))],
            ["预测加权参考单价", number(summary.get("weighted_unit_price"))],
            ["预测排除规格", refs(excluded)], ["预测模型版本", f.get("model_version")]])
    table(["结论依据", "服务返回值", "说明"],
          [[x.get("title"), x.get("value"), x.get("detail")] for x in e.get("factors") or []])

    heading("物料维度 · 完整范围")
    paragraph("本节及客户维度中的历史数量为完整历史样本期合计；预测数量为当前所选预测期合计。两者期间不同，不能直接作为同比或增长率比较。", "note")
    table(["规格", "物料", "状态", f"完整样本期历史数量 / {unit}", f"所选期预测数量 / {unit}", f"预测金额 / {currency}"], [
        [x.get("spec"), x.get("material"), STATUS.get(x.get("status"), x.get("status")),
         number(x.get("history_quantity")), number(x.get("forecast_quantity")), number(x.get("forecast_amount"))]
        for x in d.get("by_material") or []])
    table(["规格", "物料", "状态", "不可预测原因 / 说明", "单位", "币种"], [
        [x.get("spec"), x.get("material"), STATUS.get(x.get("status"), x.get("status")),
         x.get("reason"), x.get("unit"), x.get("currency")] for x in items])
    heading("客户维度 · 需求范围", "orange")
    table(["客户", f"完整样本期历史数量 / {unit}", f"所选期预测数量 / {unit}", f"预测金额 / {currency}", "不可预测项目"], [
        [x.get("customer"), number(x.get("history_quantity")), number(x.get("forecast_quantity")),
         number(x.get("forecast_amount")), refs(x.get("unpredictable_items"))] for x in d.get("by_customer") or []])
    heading("时间维度 · 历史与预测对照")
    paragraph("逐月历史对照为该预测月份的上年同月，实际历史月份单列如下。历史数量来自已纳入的历史订单；无对应历史记录时显示 —。预测数量、单价及金额为所选月份的模拟输出，不能视为已发生采购。", "note")
    table(["预测月份", "历史对照月份（上年同月）", f"上年同月历史数量 / {unit}", f"预测数量 / {unit}", f"预测单价 / {currency}/{unit}", f"预测金额 / {currency}"], [
        [x.get("month"), x.get("history_month"), number(x.get("history_quantity")), number(x.get("forecast_quantity")),
         number(x.get("forecast_unit_price")), number(x.get("forecast_amount"))] for x in d.get("by_month") or []])

    heading("历史样本与数量、价格趋势")
    hs, window = h.get("summary") or {}, h.get("window") or {}
    values([["历史样本区间", f"{display(window.get('start'))} 至 {display(window.get('end'))}"],
            ["样本订单数", number(hs.get("record_count"))], ["历史总数量", number(hs.get("total_quantity"))],
            ["历史平均单价（服务口径）", number(hs.get("avg_unit_price"))],
            ["最早 / 最近订单", f"{display(hs.get('first_date'))} / {display(hs.get('last_date'))}"],
            ["活跃月数 / 观察月数", f"{number(hs.get('active_months'))} / {number(hs.get('month_count'))}"],
            ["历史完整性标记", h.get("complete")]])
    table(["历史趋势", "前期", "本期", "变化百分比（服务原值）", "比较口径"], [
        [label, number((a.get(key) or {}).get("previous")), number((a.get(key) or {}).get("current")),
         number((a.get(key) or {}).get("change_pct")), (a.get(key) or {}).get("comparison")]
        for key, label in [("quantity_trend", "数量"), ("price_trend", "价格")]])
    table(["历史月份", f"历史数量 / {unit}", f"历史单价 / {currency}/{unit}", f"历史金额 / {currency}", "订单数"], [
        [x.get("month"), number(x.get("quantity")), number(x.get("unit_price")), number(x.get("amount")), number(x.get("orders"))]
        for x in h.get("monthly") or []])
    sample_rows = []
    for item in items:
        sample = (item.get("history") or {}).get("summary") or {}
        sample_rows.append([item.get("spec"), item.get("material"), number(sample.get("record_count")),
                            number(sample.get("total_quantity")), number(sample.get("avg_unit_price")),
                            number(sample.get("active_months")), number(sample.get("month_count"))])
    table(["规格", "物料", "样本订单数", "历史数量", "历史平均单价", "活跃月数", "观察月数"], sample_rows)

    heading("逐月预测 · 汇总与物料客户明细", "purple")
    paragraph("预测数值、置信信息和已提供的回测指标均直接引用本次API原值。MAPE未提供即保持未知；模拟标记为真的指标仅用于流程验证，不代表正式模型效果。服务未提供置信区间时，不补造上下界。", "warning")
    table(["预测月份", "规格 / 客户", f"数量 / {unit}", f"单价 / {currency}/{unit}", f"金额 / {currency}", "预测 ID", "模型版本"], [
        [x.get("month"), f"{display(x.get('spec'))} / {display(x.get('customer'))}", number(x.get("quantity")),
         number(x.get("unit_price")), number(x.get("amount")), x.get("prediction_id"), x.get("model_version")]
        for x in f.get("monthly") or []])
    details, validation = [], []
    quality = [["当前汇总", note] for note in f.get("quality_notes") or []]
    for item in items:
        item_f = item.get("forecast") or {}
        quality.extend([[item.get("spec"), note] for note in item_f.get("quality_notes") or []])
        for row in item_f.get("monthly") or []:
            details.append([row.get("month"), row.get("spec", item.get("spec")), row.get("material", item.get("material")),
                            row.get("customer"), number(row.get("quantity")), number(row.get("unit_price")),
                            number(row.get("amount")), row.get("prediction_id"), row.get("model_version")])
            validation.append([row.get("month"), row.get("spec", item.get("spec")), row.get("customer"),
                               row.get("prediction_id"), row.get("confidence"), "未提供" if row.get("backtest_mape") is None else number(row["backtest_mape"]),
                               row.get("is_synthetic")])
    table(["预测月份", "规格", "物料", "客户", f"数量 / {unit}", f"单价 / {currency}/{unit}", f"金额 / {currency}", "预测 ID", "模型版本"], details)
    heading("模型质量来源与高偏差提示", "purple")
    paragraph("结合样本量、历史覆盖和质量提示判断适用性。高偏差、样本不足与不可预测提示均保留；本报告不据模拟指标认定模型已通过真实业务验收。", "note")
    table(["范围 / 规格", "预测质量提示（含高偏差与样本限制）"], quality)
    table(["月份", "规格", "客户", "预测 ID", "置信信息（服务原值）", "API回测 MAPE（比率原值；缺失为未提供）", "模拟标记"], validation)

    heading("交付周期", "teal")
    delivery = a.get("delivery") or {}
    values([["平均交付天数", number(delivery.get("avg_days"))],
            ["最短 / 最长天数", f"{number(delivery.get('min_days'))} / {number(delivery.get('max_days'))}"],
            ["已完成 / 未完成订单", f"{number(delivery.get('completed_orders'))} / {number(delivery.get('open_orders'))}"],
            ["统计口径与限制", delivery.get("note")]])
    table(["历史月份", "平均交付天数", "订单数"], [
        [x.get("month"), number(x.get("avg_days")), number(x.get("orders"))] for x in delivery.get("monthly") or []])
    heading("客户需求变化", "orange")
    table(["客户", f"前期数量 / {unit}", f"本期数量 / {unit}", "变化百分比（服务原值）", "比较口径"], [
        [x.get("customer"), number(x.get("previous_quantity")), number(x.get("current_quantity")), number(x.get("change_pct")), x.get("comparison")]
        for x in a.get("customer_changes") or []])

    heading("当前订单、项目计划与市场影响", "orange")
    paragraph("以下为纳入本次分析的模拟上下文；当前订单来源可与历史订单及来源 ID 交叉复核。", "note")
    table(["来源 ID", "类型", "标题", "日期", "来源", "详情", "影响", "模拟标记"], [
        [x.get("id"), x.get("type"), x.get("title"), x.get("date"), x.get("source"), x.get("detail"), x.get("impact"), x.get("is_synthetic")]
        for x in a.get("context") or []])
    table(["影响因素", "分析说明", "证据引用 ID"], [
        [x.get("title"), x.get("detail"), refs(x.get("evidence_refs"))] for x in e.get("influences") or []])
    heading("预排合同量建议与依据")
    paragraph("建议仅用于模拟流程讨论，数量与期间直接引用本次分析结果，不代表已批准采购或已签订合同。", "note")
    table(["规格", "客户", f"建议数量 / {unit}", "建议期间", "建议依据", "证据引用 ID"], [
        [x.get("spec"), x.get("customer"), number(x.get("quantity")), x.get("period"), x.get("reason"), refs(x.get("evidence_refs"))]
        for x in d.get("suggestions") or []])

    heading("历史订单明细 · 可逐行追溯")
    table(["订单号", "日期", "规格", "物料", "客户", "供应商", "历史数量", "历史单价", "历史金额", "单位 / 币种"], [
        [x.get("order_id"), x.get("date"), x.get("spec"), x.get("material"), x.get("customer"), x.get("supplier"),
         number(x.get("quantity")), number(x.get("unit_price")), number(x.get("amount")),
         f"{display(x.get('unit'))} / {display(x.get('currency'))}"] for x in h.get("records") or []])
    if not h.get("records"):
        paragraph("当前范围没有可展示的匹配订单；不将服务异常或空结果解释为企业从未采购。", "note")
    table(["订单号", "预计交付日", "实际交付日", "交付天数", "来源 ID"], [
        [x.get("order_id"), x.get("expected_delivery_date"), x.get("actual_delivery_date"), number(x.get("lead_days")), x.get("source_id")]
        for x in h.get("records") or []])

    heading("来源、月度批次与适用限制")
    values([["数据性质", p.get("label")], ["模拟标记", p.get("is_synthetic")],
            ["数据截止", p.get("cutoff")], ["数据集 SHA", p.get("dataset_sha")],
            ["历史服务来源", p.get("history_source")], ["预测服务来源", p.get("forecast_source")],
            ["分析服务来源", p.get("analysis_source")], ["解释模型", e.get("analysis_model")],
            ["分析来源 ID", e.get("analysis_source_id")], ["批次月份", batch.get("month")],
            ["批次版本", batch.get("version")], ["批次生成时间", batch.get("generated_at")],
            ["本批新增订单数", number(batch.get("added_count"))], ["本批订单 ID", refs(batch.get("order_ids"))],
            ["批次数据行数", number(batch.get("dataset_rows"))], ["批次数据集 SHA", batch.get("dataset_sha")],
            ["下次更新", batch.get("next_run")]])
    model_inputs = []
    if f.get("dataset_sha") is not None:
        model_inputs.append(["模拟预测模型输入数据集 SHA", f.get("dataset_sha")])
    if "input_order_ids" in f:
        model_inputs.append(["模拟预测模型纳入的订单 ID", refs(f.get("input_order_ids"))])
    if model_inputs:
        paragraph("模型输入口径：以下数据指纹与订单清单由模拟预测服务返回，用于追溯纳入预测的输入批次；输入批次与当前筛选范围内的历史订单明细分别列示，不代表已训练或运行真实预测模型。", "note")
        values(model_inputs)
    for limitation in e.get("limitations") or []:
        paragraph(limitation, "warning")
    paragraph("报告与页面使用同一次执行结果。渲染层不重算历史统计、预测数量、单价、金额或合同建议；来源和版本仅用于追溯本次模拟执行。", "note")
    return blocks


def markdown(result):
    lines = ["# 采购需求分析报告", "", "> 模拟数据 · 流程验证 · 非真实采购决策依据", ""]
    for block in _document(result):
        if block[0] == "heading":
            lines.extend(["## " + md(block[1]), ""])
        elif block[0] == "paragraph":
            lines.extend([md(block[1]), ""])
        else:
            headers, rows = block[1:]
            lines.append("| " + " | ".join(md(x) for x in headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows or [["未提供 / 不适用"] + [None] * (len(headers) - 1)]:
                lines.append("| " + " | ".join(md(x) for x in row) + " |")
            lines.append("")
    return "\n".join(lines) + "\n"


STYLE = """
:root{color-scheme:light;--ink:#19344c;--muted:#63788b;--line:#dce6ee;--blue:#1769bf;--paper:#fff;--mono:'SFMono-Regular',Consolas,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f1f5f9;color:var(--ink);font:14px/1.75 'Avenir Next','PingFang SC','Microsoft YaHei',sans-serif}main{max-width:1288px;min-width:0;margin:28px auto;padding:0 24px 36px}.report-header{padding:0 2px 19px;border-bottom:1px solid var(--line)}.header-top,.report-meta{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.organization{font-size:12px;color:var(--muted)}.badge{display:inline-block;color:#35678f;background:#e7f1fc;border:1px solid #cddff3;padding:3px 10px;border-radius:5px;font-size:11px}h1{font-size:28px;line-height:1.4;font-weight:650;letter-spacing:-.025em;margin:14px 0 8px}.report-scope{font-size:14px;margin:0;color:#42617a;overflow-wrap:anywhere}.report-meta{justify-content:flex-start;gap:8px 22px;color:var(--muted);font-size:11px;margin:12px 0 0;overflow-wrap:anywhere}.request-id{font-family:var(--mono)}.report-nav{display:flex;gap:6px;overflow:auto;padding:15px 0;scrollbar-width:thin}.report-nav a{flex:0 0 auto;text-decoration:none;color:#48637a;padding:6px 10px;border:1px solid transparent;border-radius:5px;font-size:12px}.report-nav a:hover{background:#e5eef8;border-color:#cadcee;color:#145caa}a:focus-visible,summary:focus-visible,.table-scroll:focus-visible,.chart-scroll:focus-visible{outline:3px solid #1681cb;outline-offset:3px}.report-section{min-width:0;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:25px 28px;margin:0 0 18px;scroll-margin-top:18px}h2{display:flex;align-items:baseline;gap:11px;font-size:20px;line-height:1.5;margin:0 0 15px;break-after:avoid;color:#163e61}h2 .section-number{font:12px/1 var(--mono);color:#4184bc}h3{font-size:15px;font-weight:650;margin:24px 0 10px;color:#244d71;break-after:avoid}.section-caption{font-size:12px;color:var(--muted);margin:-6px 0 18px}p{overflow-wrap:anywhere;margin:12px 0}.lead{font-size:22px;font-weight:600;line-height:1.6;color:#175d9f;margin:12px 0}.note,.warning{padding:10px 13px;font-size:12px;border:1px solid #dfebf5;border-left:3px solid #8bb6db;border-radius:4px;background:#f5f9fd;color:#49677f}.warning{border-color:#efdfbf;border-left-color:#c79c52;background:#fffbf2;color:#7d5c2c}.decision-summary{font-size:16px;line-height:1.7;margin:8px 0 12px}.decision-summary strong{color:#155fae}.contract-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:12px 0;padding:0;list-style:none}.contract-summary li{min-width:0;padding:10px 13px;border:1px solid #dfebf5;border-radius:6px;background:#f7faff}.contract-summary span{display:block;overflow-wrap:anywhere;font-size:12px;color:#55718a}.contract-summary span:first-child{color:#294e6f}.contract-summary b{font:600 17px/1.5 var(--mono);color:#155fae}.decision-boundary{font-size:11px;color:var(--muted);margin:8px 0}.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.kpi{padding:17px 18px;background:#f7faff;border:1px solid #dfeaf5;border-radius:7px;min-width:0}.kpi-label{display:block;font-size:12px;color:#597187}.kpi-value{display:block;font:500 clamp(23px,3vw,31px)/1.35 var(--mono);letter-spacing:-.045em;color:#155fae;margin:9px 0 5px;overflow-wrap:anywhere}.kpi-unit{font-size:11px;color:var(--muted)}.table-scroll{overflow:auto;max-width:100%;margin:13px 0 18px;border:1px solid var(--line);border-radius:6px;scrollbar-width:thin;scrollbar-color:#b7cbdc #f1f6f9}table{border-collapse:separate;border-spacing:0;width:100%;font-size:12px;line-height:1.7}th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid #e7edf3;overflow-wrap:anywhere;min-width:100px}th{font-size:11px;font-weight:650;color:#46647f;background:#eff5fb;white-space:nowrap}td{max-width:350px}tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#fafcfe}tbody tr:hover{background:#f0f6fc}table.key-values{table-layout:fixed}table.key-values td{min-width:0;max-width:none}table.key-values td:first-child{width:28%;color:var(--muted);background:#f8fafc}.empty{color:var(--muted)}.subsection+.subsection{border-top:1px solid #e7edf3;margin-top:24px;padding-top:1px}.subsection>h3{font-size:16px}.trend-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.trend-card{min-width:0;padding:17px 15px 13px;border:1px solid #dfe7ef;border-radius:7px;background:#fcfdff}.trend-title{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:10px}.trend-title h3{margin:0;font-size:15px}.trend-unit{color:var(--muted);font-size:11px}.legend{display:flex;flex-wrap:wrap;gap:15px;font-size:11px;color:#526d83}.legend span{display:flex;align-items:center;gap:6px}.legend i{width:19px;border-top:2px solid #1769bf;display:block}.legend .future{border-top:2px dashed #168481}.chart-scroll{overflow:auto;max-width:100%;scrollbar-width:thin}.trend-svg{display:block;width:100%;height:auto;overflow:visible}.trend-svg text{font:11px 'Avenir Next','PingFang SC',sans-serif;fill:#61788b}.trend-svg .grid{stroke:#dfe8f0;stroke-width:1}.trend-svg .history-line{stroke:#1769bf;stroke-width:2.5;fill:none;stroke-linejoin:round;stroke-linecap:round}.trend-svg .forecast-line{stroke:#168481;stroke-width:2.5;fill:none;stroke-dasharray:5 5;stroke-linejoin:round;stroke-linecap:round}.trend-svg .history-point{fill:#fff;stroke:#1769bf;stroke-width:1.6}.trend-svg .forecast-point{fill:#fff;stroke:#168481;stroke-width:1.6}.trend-svg .boundary-label{fill:#277b7b;font-size:10px}.chart-note{color:var(--muted);font-size:11px;margin:10px 0 0}.empty-chart{padding:36px 12px;text-align:center;color:var(--muted);font-size:12px}.appendix{border:1px solid var(--line);border-radius:6px;margin:12px 0;background:#fff}.appendix summary{cursor:pointer;padding:13px 15px;color:#315b7e;font-size:13px;font-weight:600;background:#f7fafd}.appendix[open] summary{border-bottom:1px solid var(--line)}.appendix-content{padding:1px 17px 7px}.appendix-content>.subsection:first-child>h3{margin-top:17px}footer{padding:2px 4px 0;color:var(--muted);font-size:11px;overflow-wrap:anywhere}.skip-link{position:absolute;left:12px;top:-70px;z-index:10;background:#fff;padding:10px;color:#175d9f}.skip-link:focus{top:12px}
@media(max-width:900px){main{padding:0 18px 26px;margin:20px auto}.report-section{padding:23px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.trend-grid{grid-template-columns:1fr}.trend-card{padding:18px}}
@media(max-width:500px){.contract-summary{grid-template-columns:1fr}main{margin:14px auto;padding:0 10px 20px}h1{font-size:24px}.report-section{padding:19px 15px;border-radius:8px;margin-bottom:13px}h2{font-size:18px;gap:8px}.lead{font-size:19px}.kpis{gap:9px}.kpi{padding:13px 11px}.kpi-value{font-size:25px}.note,.warning{padding:10px}th,td{padding:9px}table.key-values td:first-child{width:35%}.trend-card{padding:13px 9px}.trend-title{gap:7px}.trend-unit,.legend,.chart-note{font-size:10px}.appendix-content{padding:1px 10px 5px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{@page{size:A4 landscape;margin:12mm}body{background:#fff;font-size:10px}main{max-width:none;margin:0;padding:0}.report-header{padding-bottom:12px}h1{font-size:25px}.report-nav,.skip-link{display:none}.report-section{padding:17px 0;border-width:0 0 1px;border-radius:0;margin:0}.kpis{grid-template-columns:repeat(4,minmax(0,1fr))}.kpi{padding:11px 14px}.kpi-value{font-size:23px}h2{font-size:16px;margin-bottom:12px}h3{font-size:13px}.lead{font-size:16px}.table-scroll{overflow:visible;border-radius:0}table{font-size:8px;table-layout:fixed}th{font-size:8px;white-space:normal}th,td{padding:6px;min-width:0;max-width:none;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}.note,.warning{font-size:10px;break-inside:avoid}.trend-grid{grid-template-columns:1fr 1fr}.trend-card{break-inside:avoid}.chart-scroll{overflow:visible}.chart-note,.legend{font-size:9px}.appendix{border:0;border-top:1px solid var(--line)}.appendix summary{padding:12px 0;background:none;list-style:none;cursor:default}.appendix-content{display:block!important;padding:0}details::details-content{content-visibility:visible!important;height:auto!important}details:not([open])> :not(summary){display:block!important}.subsection{break-inside:auto}footer{font-size:9px}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


STYLE += '\n/* Presentation only: service values are visible immediately and never tweened. */\n.report-header{position:relative;padding:24px 26px;border:1px solid #d3e1eb;border-radius:14px;background:linear-gradient(110deg,#fff 25%,#edf6fa 80%,#e0f1f4);overflow:hidden}\n.report-header:after{content:"";position:absolute;pointer-events:none;right:-65px;top:-100px;width:390px;height:270px;border:1px solid #76aec22b;border-radius:50%;box-shadow:0 0 0 24px #76aec210,0 0 0 52px #76aec20c;transform:rotate(-22deg)}\n.report-header>*{position:relative;z-index:1}.report-section{box-shadow:0 9px 28px #153e5a05;animation:report-arrive .65s cubic-bezier(.22,.8,.25,1) both}.report-section:nth-of-type(2){animation-delay:.08s}.report-section:nth-of-type(3){animation-delay:.15s}.trend-card .chart-scroll{animation:chart-unfold .9s cubic-bezier(.2,.7,.2,1) both}.kpi{transition:transform .2s,box-shadow .2s}.kpi:hover{transform:translateY(-3px);box-shadow:0 8px 20px #1769bf10}.motion-button{position:relative;z-index:2;border:1px solid #bdd3e1;border-radius:7px;padding:6px 12px;background:#ffffffc9;color:#275a7c;font:inherit;font-size:12px;cursor:pointer}.motion-button:hover{background:#e7f4fb}.report-nav{position:sticky;top:0;z-index:5;background:#f1f5f9ed;backdrop-filter:blur(12px)}.report-nav .motion-button{flex:0 0 auto;margin-left:auto}.motion-button:focus-visible{outline:3px solid #1681cb;outline-offset:3px}.history-first{margin:18px 0 0;padding-top:1px;border-top:1px solid #e0eaf1}.history-first h3{margin-top:14px}\n@keyframes report-arrive{from{opacity:.25;transform:translateY(14px)}to{opacity:1;transform:none}}@keyframes chart-unfold{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}\n@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*:before,*:after{animation:none!important;transition:none!important}.motion-button{display:none}}\n@media print{*,*:before,*:after{animation:none!important;transition:none!important;clip-path:none!important;opacity:1!important;transform:none!important}.motion-button{display:none}.report-header{background:white;border:0;padding:0 0 12px}.report-header:after{display:none}}\n'

def _trend_chart(result, key, title, unit):
    """Map service monthly values to SVG coordinates; never derive business values."""
    history = (result.get("history") or {}).get("monthly") or []
    forecast = (result.get("forecast") or {}).get("monthly") or []
    observed_months = sorted({str(row["month"]) for row in history + forecast if row.get("month")})
    # Fill the visual calendar only: absent months remain gaps, never business zeros.
    month_number = lambda month: int(str(month)[:4]) * 12 + int(str(month)[5:7]) - 1
    months = []
    if observed_months:
        first_month, last_month = month_number(observed_months[0]), month_number(observed_months[-1])
        months = [f"{value // 12:04d}-{value % 12 + 1:02d}" for value in range(first_month, last_month + 1)]
    values = [row.get(key) for row in history + forecast]
    valid = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    values = [value for value in values if valid(value)]
    heading = f'<div class="trend-title"><h3>{esc(title)}</h3><span class="trend-unit">{esc(unit)}</span></div>'
    legend = '<div class="legend"><span><i></i>历史样本 · 实线</span><span><i class="future"></i>模拟预测 · 虚线</span></div>'
    if not months or not values:
        return f'<article class="trend-card">{heading}{legend}<p class="empty-chart">暂无可绘制的服务数值；缺失不按零显示。</p></article>'
    # Axis padding and ticks are visual coordinates, not forecast calculations.
    low, high = min(0, min(values)), max(0, max(values))
    if low == high:
        high = low + 1
    span = high - low
    high += span * .12
    left, right, top, bottom = 62, 566, 34, 207
    first, last = month_number(months[0]), month_number(months[-1])
    x = lambda month: left + (month_number(month) - first) * (right - left) / max(1, last - first)
    y = lambda value: bottom - (value - low) / (high - low) * (bottom - top)
    svg = [f'<svg class="trend-svg" viewBox="0 0 590 262" role="img" aria-label="{esc(title)}：历史与模拟预测月度趋势"><title>{esc(title)}；单位 {esc(unit)}。横轴为实际月份，纵轴为服务返回的月度值。历史与预测分别绘制，缺失处断开。悬停数据点查看原值，详细数值见月度表。</title><text x="{left}" y="17">{esc(unit)}</text><text x="{right}" y="252" text-anchor="end">实际月份</text>']
    if forecast:
        forecast_months = [str(row["month"]) for row in forecast if row.get("month")]
        if forecast_months:
            boundary = max(left, x(min(forecast_months)) - (right - left) / max(1, last - first) / 2)
            boundary_anchor = "end" if boundary > right - 150 else "start"
            svg.append(f'<rect x="{boundary:.2f}" y="{top}" width="{right-boundary:.2f}" height="{bottom-top}" fill="#e8f6f6" rx="3"/><line x1="{boundary:.2f}" y1="{top}" x2="{boundary:.2f}" y2="{bottom}" stroke="#83b9c6" stroke-dasharray="3 4"/><text class="boundary-label" x="{min(boundary + 5, right):.2f}" y="27" text-anchor="{boundary_anchor}">预测起点 {esc(min(forecast_months))}</text>')
    for i in range(4):
        value = low + (high - low) * i / 3
        py = y(value)
        svg.append(f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{right}" y2="{py:.2f}"/><text x="{left-10}" y="{py+3:.2f}" text-anchor="end">{esc(number(value))}</text>')
    step = max(1, math.ceil((len(months) - 1) / 5))
    labels = set(range(0, len(months), step)) | {len(months) - 1}
    for i in sorted(labels):
        svg.append(f'<text x="{x(months[i]):.2f}" y="230" text-anchor="middle">{esc(months[i])}</text>')
    for rows, css, label in [(history, "history", "历史"), (forecast, "forecast", "模拟预测")]:
        indexed = {str(row["month"]): row.get(key) for row in rows if row.get("month")}
        segments, points, segment = [], [], []
        series_months = sorted(indexed)
        for month in months:
            value = indexed.get(month)
            if not valid(value):
                if segment:
                    segments.append(segment)
                    segment = []
                if series_months and series_months[0] <= month <= series_months[-1]:
                    points.append(f'<text x="{x(month):.2f}" y="{bottom+13}" text-anchor="middle"><title>{esc(month)} · {label}：缺失（—），不按零显示</title>×</text>')
                continue
            px, py = x(month), y(value)
            segment.append(f'{px:.2f},{py:.2f}')
            points.append(f'<circle class="{css}-point" cx="{px:.2f}" cy="{py:.2f}" r="3"><title>{esc(month)} · {label}原值：{esc(display(value))} {esc(unit)}</title></circle>')
        if segment:
            segments.append(segment)
        svg.extend(f'<polyline class="{css}-line" points="{" ".join(segment)}"/>' for segment in segments if len(segment) > 1)
        svg.extend(points)
    svg.append('</svg>')
    forecast_note = "预测区域为浅青底，历史与预测不连线。" if forecast else "本次无可预测结果，仅展示已有历史。"
    return f'<article class="trend-card">{heading}{legend}<div class="chart-scroll" tabindex="0" role="region" aria-label="{esc(title)}，完整月份全景">{"".join(svg)}</div><p class="chart-note">{forecast_note}× 为缺失月份标记，缺失值留空；横轴首尾为完整展示区间。</p></article>'


def html_report(result):
    # Reorder the shared document for reading; keep every original block and value.
    sections, current = [], None
    for block in _document(result):
        if block[0] == "heading":
            current = {"title": block[1], "blocks": []}
            sections.append(current)
        else:
            current["blocks"].append(block)

    def render_blocks(blocks):
        rendered = []
        for block in blocks:
            if block[0] == "paragraph":
                rendered.append(f'<p class="{esc(block[2])}">{esc(block[1]).replace(chr(10), "<br>")}</p>')
            else:
                headers, rows = block[1:]
                css = ' class="key-values"' if headers == ["项目", "本次结果"] else ""
                head = "".join(f'<th scope="col">{esc(x)}</th>' for x in headers)
                data = "".join("<tr>" + "".join(f"<td>{esc(x).replace(chr(10), '<br>')}</td>" for x in row) + "</tr>" for row in rows)
                if not data:
                    data = f'<tr><td class="empty" colspan="{len(headers)}">未提供 / 不适用</td></tr>'
                rendered.append(f'<div class="table-scroll" tabindex="0" role="region" aria-label="{esc(headers[0])}数据表"><table{css}><thead><tr>{head}</tr></thead><tbody>{data}</tbody></table></div>')
        return "".join(rendered)

    def subsection(index, blocks=None):
        source = sections[index - 1]
        return f'<div class="subsection" id="source-{index}"><h3>{esc(source["title"])}</h3>{render_blocks(source["blocks"] if blocks is None else blocks)}</div>'

    def panel(index, title, content, caption=""):
        caption_html = f'<p class="section-caption">{esc(caption)}</p>' if caption else ""
        return f'<section class="report-section" id="section-{index}" aria-labelledby="title-{index}"><h2 id="title-{index}"><span class="section-number" aria-hidden="true">{index:02d}</span>{esc(title)}</h2>{caption_html}{content}</section>'

    def appendix(title, content, opened=False):
        return f'<details class="appendix"{" open" if opened else ""}><summary>{esc(title)}</summary><div class="appendix-content">{content}</div></details>'

    unit, currency = display(result.get("unit")), display(result.get("currency"))
    summary = (result.get("forecast") or {}).get("summary") or {}
    sample = (result.get("history") or {}).get("summary") or {}
    period = result.get("period") or {}
    customer = '全部客户' if result.get('customer') == 'all' else result.get('customer')
    kpis = [
        ("预测数量小计", summary.get("quantity"), unit),
        ("预测金额小计", summary.get("amount"), currency),
        ("预测加权参考单价", summary.get("weighted_unit_price"), f"{currency} / {unit}"),
        ("历史样本订单", sample.get("record_count"), "笔 · 完整历史样本期"),
    ]
    highlights = ''.join(f'<div class="kpi"><span class="kpi-label">{esc(label)}</span><strong class="kpi-value">{esc(number(value))}</strong><span class="kpi-unit">{esc(suffix)}</span></div>' for label, value, suffix in kpis)
    charts = _trend_chart(result, "quantity", "月度需求数量", unit) + _trend_chart(result, "unit_price", "月度参考单价", f"{currency} / {unit}")

    # Keep verbose scope/model fields in the appendix rather than ahead of the conclusion.
    conclusion, summary_blocks = [], []
    for block in sections[1]["blocks"]:
        (summary_blocks if block[0] == "table" and block[1] == ["项目", "本次结果"] else conclusion).append(block)
    limitations = (result.get("explanation") or {}).get("limitations") or []
    source_blocks, limit_blocks = [], []
    for block in sections[13]["blocks"]:
        (limit_blocks if block[0] == "paragraph" and block[2] == "warning" and block[1] in limitations else source_blocks).append(block)
    # A short decision summary uses service values directly; the full original text
    # and evidence tables remain in the adjacent expandable document.
    if summary.get("quantity") is not None:
        decision = f'<p class="decision-summary">{esc(period.get("start"))} 至 {esc(period.get("end"))}，预测数量参考 <strong>{esc(number(summary.get("quantity")))} {esc(unit)}</strong>，金额参考 <strong>{esc(number(summary.get("amount")))} {esc(currency)}</strong>。</p>'
    else:
        explanation = result.get("explanation") or {}
        decision = f'<p class="decision-summary"><strong>{esc(STATUS.get(result.get("status"), result.get("status")))}</strong> · {esc(explanation.get("headline") or result.get("message"))}</p>'
    excluded = (result.get("report_dimensions") or {}).get("excluded_specs") or []
    scope_warning = f'<p class="warning">预测与合同量参考只覆盖可预测部分；未计入：{esc(refs(excluded))}。缺失不按零处理。</p>' if excluded else ""
    quality_warnings = [note for note in (result.get("forecast") or {}).get("quality_notes") or []
                        if "偏差" in str(note) or "不足" in str(note)]
    warning_html = "".join(f'<p class="warning">模型提示（服务原值）：{esc(note)}</p>' for note in quality_warnings)
    suggestions = (result.get("report_dimensions") or {}).get("suggestions") or []
    suggestion_cards = "".join(f'<li><span><strong>{esc(row.get("spec"))}</strong> / {esc(row.get("customer"))}</span><span>{esc(row.get("period"))} · 参考 <b>{esc(number(row.get("quantity")))}</b> {esc(unit)}</span></li>' for row in suggestions)
    suggestion_html = f'<ul class="contract-summary" aria-label="全部预排合同量参考">{suggestion_cards}</ul>' if suggestions else '<p class="decision-boundary">本次没有可用的预排合同量参考。</p>'
    limits_html = '<h3>适用条件与范围限制</h3>' + render_blocks(limit_blocks) if limit_blocks else ""
    full_conclusion = appendix("完整结论、合同建议与证据 · 展开查看", subsection(2, conclusion) + subsection(12) + limits_html)
    compact_conclusion = decision + scope_warning + warning_html + suggestion_html + '<p class="decision-boundary">仅供模拟备货讨论；实际需求须与客户核实，不构成采购承诺。</p>' + full_conclusion
    history_fallback = summary.get("quantity") is None and result.get("status") in ("unpredictable", "no_history")
    history_evidence = subsection(13)
    if history_fallback:
        compact_conclusion += '<div class="history-first"><h3>已转历史订单查询</h3><p>' + esc((result.get("explanation") or {}).get("body") or result.get("message")) + '</p><p>以下为本次查询返回的历史记录，不能作为未来预测。缺失预测不按零处理。</p>' + history_evidence + '</div>'
    contents = [
        panel(1, "结论与预排合同量参考", compact_conclusion),
        panel(2, "关键数量与价格", f'<div class="kpis" aria-label="本次分析关键数据">{highlights}</div><p class="chart-note">预测指标仅为所选预测期小计；历史样本订单数对应完整样本期。不可预测项与缺失值均不按零计入。</p>'),
        panel(3, "历史数量与价格 · 月度预测对照", f'<div class="trend-grid">{charts}</div><p class="chart-note">两图按实际月份展示完整历史与所选预测期；数量、单价均引用服务原值。多物料单价为服务汇总口径。悬停数据点可查原值，月度明细可逐行核对。</p>', "实线为历史样本，虚线为模拟预测；浅青区域标出预测范围，缺失值不连线。"),
        panel(4, "按物料、客户与时间查看", subsection(3) + subsection(4) + subsection(5)),
        panel(5, "月度预测明细", subsection(7)),
        panel(6, "交付、客户与上下文依据", subsection(9) + subsection(10) + subsection(11)),
        panel(7, "样本、模型、来源与完整历史", appendix("历史样本、月度数量价格与趋势口径", subsection(6)) + appendix("模型质量、模拟验证与预测汇总字段", subsection(8) + '<div class="subsection"><h3>预测汇总字段</h3>' + render_blocks(summary_blocks) + '</div>') + appendix("来源、批次与运行参数", subsection(14, source_blocks) + subsection(1)) + ("" if history_fallback else appendix("完整历史订单与交付明细 · 可逐行追溯", history_evidence)), "保留本次结果的全部字段与证据。展开查看完整记录；打印时自动展开全部内容。"),
    ]
    navigation = ''.join(f'<a href="#section-{index}">{esc(label)}</a>' for index, label in [(1, "结论与合同量"), (2, "关键指标"), (3, "量价趋势"), (4, "三维度"), (5, "月度明细"), (6, "交付与依据"), (7, "样本与溯源")])
    # Opening details before printing also supports browsers without ::details-content.
    print_script = """<script>let printDetails=[];addEventListener('beforeprint',()=>{printDetails=[...document.querySelectorAll('details:not([open])')];printDetails.forEach(item=>item.open=true)});addEventListener('afterprint',()=>{printDetails.forEach(item=>item.open=false);printDetails=[]});</script>"""
    motion_script = """<script>(()=>{const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;const unfold=item=>item.animate([{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0 0 0 0)'}],{duration:950,easing:'cubic-bezier(.2,.7,.2,1)'});if(!reduced()&&'IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){unfold(entry.target);observer.unobserve(entry.target)}}),{threshold:.15});document.querySelectorAll('.trend-card .chart-scroll').forEach(item=>observer.observe(item))}document.getElementById('replay-motion').addEventListener('click',()=>{if(reduced())return;document.querySelectorAll('.report-section').forEach(item=>{const rect=item.getBoundingClientRect();if(rect.bottom>0&&rect.top<innerHeight)item.animate([{opacity:.3,transform:'translateY(12px)'},{opacity:1,transform:'none'}],{duration:550,easing:'cubic-bezier(.22,.8,.25,1)'})});document.querySelectorAll('.trend-card .chart-scroll').forEach(item=>{const rect=item.getBoundingClientRect();if(rect.bottom>0&&rect.top<innerHeight)unfold(item)})})})();</script>"""
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(result.get('spec'))} · 采购需求分析报告</title><style>{STYLE}</style></head>
<body><a class="skip-link" href="#section-1">跳至分析结论</a><main><header class="report-header"><div class="header-top"><span class="organization">中航供应链 · 月度采购需求分析</span><span><span class="badge">模拟数据 · 流程验证</span></span></div><h1>采购需求分析报告</h1><p class="report-scope">{esc(result.get('spec'))} · {esc(result.get('material'))} · {esc(customer)}　/　{esc(period.get('label'))}　/　{esc(STATUS.get(result.get('status'), result.get('status')))}</p><p class="report-meta"><span>生成时间 {esc(result.get('generated_at'))}</span><span class="request-id">查询编号 {esc(result.get('request_id'))}</span></p></header><nav class="report-nav" aria-label="报告章节">{navigation}<button class="motion-button" id="replay-motion" type="button">↻ 重播图表动效</button></nav>{''.join(contents)}<footer>HTML、Markdown 和 JSON 导出引用同一次分析结果。当前业务数据和预测 API 为模拟，解释来自已核验的平台 Agent / Skill；正式预测 API、历史 NL2SQL 及业务效果仍待接入与验收。</footer></main>{print_script}{motion_script}</body></html>'''


def save_report(result, directory, public_prefix=""):
    root = Path(directory) / result["request_id"]
    root.mkdir(parents=True, exist_ok=False)
    result["reports"] = {
        "html_url": f"{public_prefix}/api/reports/{result['request_id']}/report.html",
        "markdown_url": f"{public_prefix}/api/reports/{result['request_id']}/report.md",
        "json_url": f"{public_prefix}/api/reports/{result['request_id']}/result.json",
    }
    blobs = {"report.html": html_report(result).encode("utf-8"), "report.md": markdown(result).encode("utf-8"), "result.json": json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")}
    for name, data in blobs.items():
        (root / name).write_bytes(data)
    return blobs
