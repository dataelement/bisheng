"""Mock model and mock explanation provider; no real ML/LLM effectiveness claim."""
from decimal import Decimal, ROUND_HALF_UP
import uuid
import re
from store import add_month

def money(v):
    return float(Decimal(str(v)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))

def forecast_response(spec, customer, start, months, batch):
    if type(months) != int or not 1 <= months <= 12 or not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", start) or customer not in ('all','演示客户甲','演示客户乙'):
        raise ValueError('模拟预测周期或客户不支持')
    if spec == "TEST-API-ERROR": raise RuntimeError("模拟预测服务故障")
    if spec not in ("189A1002-1", "186A3107-751", "ZERO-PRED-001"): return 0
    customers = ["演示客户甲", "演示客户乙"] if customer == "all" else [customer]
    rows=[]
    for c in customers:
        for offset in range(months):
            month=add_month(start,offset);season=int(month[5:])-1
            base=([52,49,58,54,57,63,60,61,65,62,68,71] if spec=="189A1002-1" else [30,25,40,22,38,28,45,35,31,42,29,39])[season]
            adjustment = int(batch.get('new_order_totals',{}).get(spec+'|'+c,0) // 20)
            quantity=0 if spec=="ZERO-PRED-001" else (base if c=="演示客户甲" else round(base*.6)) + adjustment
            price=money((47.1 if spec=="189A1002-1" else 63.4) + season*.12 + (int(month[:4])-2026)*.4)
            rows.append({"month":month,"spec":spec,"material":"航空结构连接件" if spec=="189A1002-1" else "航空装配连接件","customer":c,
                         "quantity":quantity,"unit_price":price,"amount":money(Decimal(str(quantity))*Decimal(str(price))),
                         "prediction_id":f"P-{batch['version']}-{spec}-{c[-1]}-{month}","model_version":f"SIM-TS-{batch['month']}",
                         "confidence":"低" if spec=="186A3107-751" else "中","backtest_mape":.48 if spec=="186A3107-751" else .18,"is_synthetic":True})
    return {"spec":spec,"customer":customer,"start_month":start,"months":months,"monthly":rows,"unit":"件","currency":"CNY","source":"synthetic_monthly_model","model_version":f"SIM-TS-{batch['month']}","dataset_sha":batch['dataset_sha'],"input_order_ids":batch.get('included_order_ids',[])}

def analysis_response(facts):
    status=facts["status"];history=facts["history"];summary=history["summary"];analytics=facts["analytics"]
    if status=="predicted":headline="月度需求预测已生成";body="数量与单价由模拟时序模型逐月返回；结合历史、当期订单、项目计划与市场快照形成以下说明。采购安排仍需与客户实际下达需求核实。"
    elif status=="mixed":headline="部分物料可预测，缺乏依据的物料保留历史";body="月度合计仅包含有预测结果的物料，未将不可预测项视为零需求。请分别核对各物料的样本与模型限制。"
    elif status=="no_history":headline="新增件号样本不足，需离线重新计算";body="当前测试范围无匹配历史，不能即时生成预测。可登记补样本后的离线重新计算任务，不代表企业从未采购。"
    else:headline="历史需求稀疏，暂不提供月度预测";body=f"模拟模型返回不可预测；当前窗口共{summary['record_count']}笔记录，仅{summary['active_months']}个有需求月份。重复观察不足，保留历史事实并说明限制，不使用历史均值伪造预测。"
    factors=[{"title":"历史样本","value":f"{summary['record_count']}笔","detail":f"{history['window']['start']} 至 {history['window']['end']}"},
             {"title":"有需求月份","value":f"{summary['active_months']} / {summary['month_count']}","detail":"完整模拟窗口内至少有一笔采购的月份"},
             {"title":"实际交付周期","value":f"{analytics['delivery']['avg_days']}天" if analytics['delivery']['avg_days'] is not None else "暂无完成交付样本","detail":"实际交付日期减采购日期，未交付不计零天"}]
    influences=[{"title":"交付周期影响","detail":analytics["delivery"]["note"],"evidence_refs":["STAT-DELIVERY"]},
                {"title":"客户需求变化","detail":"比较客户最近三个数据月份与前一组三个月的数量；含当月未结束期间，不据此认定长期增长。","evidence_refs":["STAT-CUSTOMER"]}]
    influences += [{"title":x["title"],"detail":x["detail"]+" "+x["impact"],"evidence_refs":[x["id"]]} for x in analytics["context"]]
    suggestions=[]
    for item in facts["items"]:
        if not item["forecast"]:continue
        for customer in sorted({r["customer"] for r in item["forecast"]["monthly"]}):
            rows=[r for r in item["forecast"]["monthly"] if r["customer"]==customer]
            suggestions.append({"spec":item["spec"],"customer":customer,"quantity":sum(r["quantity"] for r in rows),"period":facts["period"]["label"],
                                "reason":"预排合同量参考直接取本次模拟模型月度数量合计，先按客户需求与项目计划复核，再安排采购；不自动下单。",
                                "evidence_refs":[r["prediction_id"] for r in rows]+["PLAN-001"]})
    return {"headline":headline,"body":body,"factors":factors,"limitations":["全部订单、模型结果及解释为模拟，不能用来证明预测准确度。","实际需求以客户下达为准；数量建议供备货安排参考，不是采购承诺。","高偏差物料单独标明；不可预测、无历史与服务失败分别处理。"],
            "influences":influences,"analysis_model":"模拟大模型分析服务（未调用真实大模型）","analysis_source_id":"SIM-ANALYSIS-"+uuid.uuid4().hex,"suggestions":suggestions}
