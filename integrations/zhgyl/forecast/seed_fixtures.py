# coding: utf-8
from pathlib import Path
from datetime import date, timedelta
import json

rows=[]
for idx in range(24):
    y=2024+(10+idx)//12; m=(10+idx)%12+1
    if idx<12 and idx%2: continue
    d=date(y,m,7)
    rows.append(dict(order_id=f"SIM-A-{idx+1:03}",spec="189A1002-1",material="航空结构连接件",customer="演示客户甲" if idx%2==0 else "演示客户乙",date=d.isoformat(),quantity=35+idx*2+(idx%3)*7,unit_price=round(41+idx*.22,2),supplier="演示供应商甲",expected_delivery_date=(d+timedelta(days=18)).isoformat(),actual_delivery_date=(d+timedelta(days=14+idx%7)).isoformat(),source_id=f"ORDER-A-{idx+1:03}"))
for idx in range(8):
    d=date(2025+idx//4,(idx%4)*3+1,10)
    rows.append(dict(order_id=f"SIM-B-{idx+1:03}",spec="186A3107-751",material="航空装配连接件",customer="演示客户乙" if idx%2 else "演示客户甲",date=d.isoformat(),quantity=24+idx*3,unit_price=round(58+idx*.7,2),supplier="演示供应商乙",expected_delivery_date=(d+timedelta(days=22)).isoformat(),actual_delivery_date=(d+timedelta(days=20+idx%9)).isoformat(),source_id=f"ORDER-B-{idx+1:03}"))
for idx,(ds,q,p) in enumerate([("2025-02-07",24,18.5),("2026-05-09",80,22)]):
    d=date.fromisoformat(ds)
    rows.append(dict(order_id=f"SIM-C-{idx+1:03}",spec="BACB30YP8K9",material="航空紧固件",customer="演示客户乙",date=ds,quantity=q,unit_price=p,supplier="演示供应商丙",expected_delivery_date=(d+timedelta(days=15)).isoformat(),actual_delivery_date=(d+timedelta(days=17+idx)).isoformat(),source_id=f"ORDER-C-{idx+1:03}"))
incoming=[]
for spec,name,cust,q,p,day,n in [("189A1002-1","航空结构连接件","演示客户甲",70,47.1,9,1),("186A3107-751","航空装配连接件","演示客户乙",32,63.4,16,2)]:
    d=date(2026,11,day)
    incoming.append(dict(order_id=f"SIM-NEW-{n:03}",spec=spec,material=name,customer=cust,date=d.isoformat(),quantity=q,unit_price=p,supplier="演示供应商甲" if n==1 else "演示供应商乙",expected_delivery_date=(d+timedelta(days=25)).isoformat(),actual_delivery_date=None,source_id=f"CURRENT-ORDER-{n:03}"))
incoming.append(dict(order_id='SIM-DEC-001',spec='189A1002-1',material='航空结构连接件',customer='演示客户甲',date='2026-12-05',quantity=40,unit_price=47.5,supplier='演示供应商甲',expected_delivery_date='2026-12-30',actual_delivery_date=None,source_id='CURRENT-DEC-001'))
data={"source":"synthetic_fixture","label":"订单、预测及分析均为模拟，仅验证文档流程和展示","window":{"start":"2024-11-01","end":"2026-11-23"},"cutoff":"2026-11-23","materials":{"189A1002-1":{"material":"航空结构连接件","unit":"件","currency":"CNY"},"186A3107-751":{"material":"航空装配连接件","unit":"件","currency":"CNY"},"BACB30YP8K9":{"material":"航空紧固件","unit":"件","currency":"CNY"},"ZERO-PRED-001":{"material":"零值边界样例","unit":"件","currency":"CNY"}},"customers":["演示客户甲","演示客户乙"],"records":rows,"incoming_orders":incoming,"context":[{"id":"PLAN-001","type":"project_plan","title":"演示装配项目一季度备货计划","date":"2026-11-18","source":"合成项目计划台账 PLAN-001","detail":"演示项目计划在下一季度集中装配，备货建议须与客户订单复核。","impact":"可能影响采购节奏；不能单凭计划推算确定采购承诺。","is_synthetic":True},{"id":"MKT-001","type":"market","title":"演示原材料价格指数","date":"2026-11-20","source":"合成市场信息快照 MKT-001","detail":"模拟材料指数较上一期上涨3.2%；本数据不是实时市场行情。","impact":"用于说明单价变化的潜在影响，不作为确定性涨价因果。","is_synthetic":True}]}
if __name__=="__main__":
    output = Path(__file__).parent / "skill/procurement-forecast-fast/assets/orders.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("initial",len(rows),"incoming",len(incoming))
