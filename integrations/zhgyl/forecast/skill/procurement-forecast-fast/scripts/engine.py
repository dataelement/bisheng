# coding: utf-8
"""Monthly mock contracts: calculate facts once; model and explanation via HTTP."""
from __future__ import annotations
import json, re, sqlite3, math, urllib.request, urllib.parse, urllib.error, http.client, uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from store import add_month, now_text, digest


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def summarize_forecast(rows):
    quantity=sum(Decimal(str(r['quantity'])) for r in rows)
    amount=sum(Decimal(str(r['amount'])) for r in rows)
    return {'quantity':float(quantity),'amount':float(amount),'weighted_unit_price':money(amount/quantity) if quantity else None}


def merge_months(rows):
    output=[]
    for month in sorted({r['month'] for r in rows}):
        group=[r for r in rows if r['month']==month];s=summarize_forecast(group)
        output.append({'month':month,'spec':'汇总','customer':'汇总','quantity':s['quantity'],'unit_price':s['weighted_unit_price'],'amount':s['amount']})
    return output


class HistoryRepository:
    def __init__(self, source):self.source=source
    def read(self,specs,customer='all'):
        fields=['order_id','spec','material','customer','date','quantity','unit_price','supplier','expected_delivery_date','actual_delivery_date','source_id']
        with sqlite3.connect(':memory:') as conn:
            conn.row_factory=sqlite3.Row
            conn.execute('CREATE TABLE orders(order_id TEXT,spec TEXT,material TEXT,customer TEXT,date TEXT,quantity REAL,unit_price REAL,supplier TEXT,expected_delivery_date TEXT,actual_delivery_date TEXT,source_id TEXT)')
            conn.executemany('INSERT INTO orders VALUES('+','.join('?' for _ in fields)+')',[[r.get(k) for k in fields] for r in self.source['records']])
            conn.execute('PRAGMA query_only=ON')
            query='SELECT * FROM orders WHERE spec IN ('+','.join('?' for _ in specs)+') AND date>=? AND date<=?';args=list(specs)+[self.source['window']['start'],self.source['window']['end']]
            if customer!='all':query+=' AND customer=?';args.append(customer)
            records=[dict(r) for r in conn.execute(query+' ORDER BY date,order_id',args)]
        for r in records:
            r.update(amount=money(Decimal(str(r['quantity']))*Decimal(str(r['unit_price']))),unit='件',currency='CNY')
            r['lead_days']=(date.fromisoformat(r['actual_delivery_date'])-date.fromisoformat(r['date'])).days if r['actual_delivery_date'] else None
        start=self.source['window']['start'][:7];end=self.source['window']['end'][:7]
        monthly=[];month=start
        while month<=end:
            matched=[r for r in records if r['date'][:7]==month]
            q=sum(Decimal(str(r['quantity'])) for r in matched);a=sum(Decimal(str(r['amount'])) for r in matched)
            monthly.append({'month':month,'quantity':float(q),'unit_price':money(a/q) if q else None,'amount':float(a),'orders':len(matched)})
            month=add_month(month,1)
        q=sum(Decimal(str(r['quantity'])) for r in records);a=sum(Decimal(str(r['amount'])) for r in records)
        summary={'record_count':len(records),'total_quantity':float(q),'avg_unit_price':money(a/q) if q else None,'first_date':records[0]['date'] if records else None,'last_date':records[-1]['date'] if records else None,'active_months':sum(x['orders']>0 for x in monthly),'month_count':len(monthly)}
        return {'records':records,'monthly':monthly,'summary':summary,'window':self.source['window'],'complete':True}


class GatewayError(Exception):pass
class ForecastGateway:
    def __init__(self,base_url,timeout=3):
        parsed=urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:raise ValueError('无效服务地址')
        self.base_url=base_url.rstrip('/');self.timeout=timeout
    def _request(self,path,request_id,body=None):
        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
        request=urllib.request.Request(self.base_url+path,data=data,headers={'Content-Type':'application/json','X-Request-ID':request_id})
        try:
            with urllib.request.urlopen(request,timeout=self.timeout) as response:
                raw=response.read(1_000_001)
                if len(raw)>1_000_000:raise GatewayError('服务回包过大')
                return json.loads(raw)
        except (urllib.error.URLError,TimeoutError,OSError,UnicodeDecodeError,json.JSONDecodeError,http.client.HTTPException) as exc:
            code=f'HTTP {exc.code}' if isinstance(exc,urllib.error.HTTPError) else '超时或无效回包'
            if isinstance(exc,urllib.error.HTTPError):exc.close()
            raise GatewayError('服务调用失败：'+code) from exc
    def predict(self,spec,customer,start,months,request_id):
        return self._request('/api/forecast?'+urllib.parse.urlencode({'spec':spec,'customer':customer,'start_month':start,'months':months}),request_id)
    def explain(self,facts,request_id):return self._request('/api/explanation',request_id,facts)


def validate_prediction(payload,spec,customer,start,months,expected_synthetic=True,expected_customers=None):
    if type(payload) in (int,float) and payload==0:return None
    if not isinstance(payload,dict) or any(payload.get(k)!=v for k,v in [('spec',spec),('customer',customer),('start_month',start),('months',months)]):raise GatewayError('预测型号、客户或期间不匹配')
    customers=(expected_customers if expected_customers is not None else ['演示客户甲','演示客户乙']) if customer=='all' else [customer]
    expected={(add_month(start,i),c) for i in range(months) for c in customers};seen=set();rows=payload.get('monthly')
    if not isinstance(rows,list) or len(rows)!=len(expected) or payload.get('unit')!='件' or payload.get('currency')!='CNY':raise GatewayError('月度预测不完整或单位不符')
    for row in rows:
        if not isinstance(row,dict):raise GatewayError('无效月度记录')
        key=(row.get('month'),row.get('customer'))
        if key not in expected or key in seen or row.get('spec')!=spec:raise GatewayError('月份缺失、重复或物料不匹配')
        seen.add(key)
        for field in ('quantity','unit_price','amount'):
            v=row.get(field)
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1e12:raise GatewayError('月度数值无效')
        quality=row.get('backtest_mape')
        if quality is not None and (type(quality) not in (int,float) or not math.isfinite(quality) or not 0<=quality<=1):raise GatewayError('预测质量口径无效')
        if money(Decimal(str(row['quantity']))*Decimal(str(row['unit_price'])))!=row['amount']:raise GatewayError('预测金额或质量口径不一致')
        if not isinstance(row.get('prediction_id'),str) or not row['prediction_id'].strip() or not isinstance(row.get('model_version'),str) or not row['model_version'].strip() or type(row.get('is_synthetic')) is not bool or (expected_synthetic is not None and row['is_synthetic'] is not expected_synthetic):raise GatewayError('预测来源或模拟标识不完整')
    if not isinstance(payload.get('dataset_sha'),str) or not payload['dataset_sha'].strip():raise GatewayError('预测数据集标识缺失')
    if not isinstance(payload.get('model_version'),str) or not payload['model_version'].strip():raise GatewayError('预测模型版本缺失')
    if not isinstance(payload.get('input_order_ids',[]),list) or any(not isinstance(x,str) or not x for x in payload.get('input_order_ids',[])):raise GatewayError('预测输入订单标识无效')
    notes=['模型逐月直接输出，不是将年度总数平均拆分。']
    qualities=[r['backtest_mape'] for r in rows if r.get('backtest_mape') is not None]
    if len(qualities)<len(rows):notes.append('预测API未提供全部月份的模型质量指标（MAPE）；未提供的指标保持未知，不代表模型已通过评测。')
    if any(value>.3 for value in qualities):notes.append('回测偏差较大（最高'+str(round(max(qualities)*100,1))+'%），需人工复核。')
    return {'monthly':rows,'summary':summarize_forecast(rows),'quality_notes':notes,'model_version':payload['model_version'],'dataset_sha':payload.get('dataset_sha'),'input_order_ids':payload.get('input_order_ids',[])}


def resolve_scope(query,source,spec,customer,start,months):
    query=str(query or '').strip();known=list(source['materials'])+['NEW-PART-001','TEST-API-ERROR']
    hits=[x for x in known if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(x)+r'(?![A-Za-z0-9_-])',query,re.I)]
    candidates=[x.upper() for x in re.findall(r'(?<![A-Za-z0-9_-])[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+(?![A-Za-z0-9_-])',query) if not re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?',x)]
    hits=list(dict.fromkeys(hits+candidates))
    labelled=re.search(r'(?:型号|件号|规格)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{1,79})',query)
    if labelled and labelled[1].upper() not in hits: hits.append(labelled[1].upper())
    all_requested=bool(re.search('全部物料|所有物料|全部型号|所有型号',query))
    if len(hits)>1 and not all_requested:raise ValueError('请选一个型号，或选择“全部物料”查看多物料报告。')
    if all_requested:spec='all'
    elif hits:spec=hits[0]
    if not spec:
        raise ValueError('请输入规格型号或选择全部物料。')
    if spec!='all' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._ ×/-]{1,79}',str(spec)):raise ValueError('请核对规格型号。')
    customer_hits=[name for name in source['customers'] if name in query]
    if re.search('全部客户|所有客户',query) or len(customer_hits)==len(source['customers']):customer='all'
    elif len(customer_hits)==1:customer=customer_hits[0]
    elif len(customer_hits)>1:raise ValueError('请明确一个客户或选择全部客户。')
    if customer not in source['customers']+['all']:raise ValueError('当前测试客户不存在，请重新选择。')
    mapping={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}
    duration=re.search(r'(?:未来|接下来|起|开始)\s*(\d+|[一二两三四五六七八九十]+)\s*(?:个)?月',query)
    if duration:months=int(duration[1]) if duration[1].isdigit() else mapping.get(duration[1],0)
    if re.search(r'未来一年|未来1年',query):months=12
    if re.search('下个月|下月',query):months=1
    if '半年' in query: months=6
    year=re.search(r'(20\d{2})年',query)
    explicit_month=re.search(r'(20\d{2})[-年](\d{1,2})(?:月)?',query)
    if explicit_month:start=f'{int(explicit_month[1]):04}-{int(explicit_month[2]):02}'
    elif year:
        start=year[1]+'-01'
        if not duration and '半年' not in query: months=12
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',str(start)) or type(months)!=int or not 1<=months<=12:raise ValueError('请选择有效起始月份及1—12个月的周期。')
    if re.search('未来三年|未来两年|未来2年|下周|明天|按日',query):raise ValueError('当前模拟服务提供按月、最多12个月预测，请明确月份。')
    specs=[s for s in source['materials'] if s!='ZERO-PRED-001'] if spec=='all' else [str(spec).upper()]
    return {'specs':specs,'customer':customer,'start_month':start,'months':months}


def build_analytics(history,source,selected_customer='all'):
    months=history['monthly'];previous=months[-6:-3];current=months[-3:]
    comparison=f"{previous[0]['month']}—{previous[-1]['month']} 对比 {current[0]['month']}—{current[-1]['month']}（含当月截至{source['cutoff']}）"
    def change(a,b):return round((b-a)/a*100,1) if a else None
    def price(rows):
        q=sum(r['quantity'] for r in rows);return money(sum(Decimal(str(r['amount'])) for r in rows)/Decimal(str(q))) if q else None
    pq=sum(r['quantity'] for r in previous);cq=sum(r['quantity'] for r in current);pp=price(previous);cp=price(current)
    complete=[r for r in history['records'] if r['lead_days'] is not None];days=[r['lead_days'] for r in complete]
    delivery_months=[]
    for m in months:
        ds=[r['lead_days'] for r in complete if r['date'][:7]==m['month']]
        delivery_months.append({'month':m['month'],'avg_days':round(sum(ds)/len(ds),1) if ds else None,'orders':len(ds)})
    customer_changes=[]
    for customer in source['customers']:
        if selected_customer!='all' and customer!=selected_customer: continue
        a=sum(r['quantity'] for r in history['records'] if r['customer']==customer and previous[0]['month']<=r['date'][:7]<=previous[-1]['month'])
        b=sum(r['quantity'] for r in history['records'] if r['customer']==customer and current[0]['month']<=r['date'][:7]<=current[-1]['month'])
        customer_changes.append({'customer':customer,'previous_quantity':a,'current_quantity':b,'change_pct':change(a,b),'comparison':comparison})
    context=[dict(x) for x in source['context']]
    for r in history['records']:
        if r['date'][:7]==source['batch']['month']:
            context.insert(0,{'id':r['source_id'],'type':'current_order','title':f"当期订单 {r['order_id']}",'date':r['date'],'source':r['source_id'],'detail':f"{r['customer']}，{r['spec']}，{r['quantity']:g}件，单价{r['unit_price']:g} CNY。",'impact':'已纳入当月样本；实际交付尚待确认，不将期望交付当成完成。','is_synthetic':True})
    avg=round(sum(days)/len(days),1) if days else None
    note=f"{len(days)}笔已完成交付的平均周期为{avg}天；{len(history['records'])-len(days)}笔未完成交付不计入平均。" if days else '当前没有完成交付样本，不能估算交付周期。'
    return {'quantity_trend':{'previous':pq,'current':cq,'change_pct':change(pq,cq),'comparison':comparison},'price_trend':{'previous':pp,'current':cp,'change_pct':change(pp,cp) if pp is not None and cp is not None else None,'comparison':comparison},'delivery':{'avg_days':avg,'min_days':min(days) if days else None,'max_days':max(days) if days else None,'completed_orders':len(days),'open_orders':len(history['records'])-len(days),'monthly':delivery_months,'note':note},'customer_changes':customer_changes,'context':context}


def analyze(query,gateway,source,spec=None,customer='all',start_month='2026-12',months=12):
    result={'ok':True,'request_id':uuid.uuid4().hex,'status':'needs_input','message':'','spec':'','material':'','customer':customer,'unit':'件','currency':'CNY','period':{},'history':None,'forecast':None,'items':[],'analytics':None,'report_dimensions':None,'explanation':{'headline':'','body':'','factors':[],'limitations':[]},'steps':[],'reports':None,'generated_at':now_text(),'batch':source['batch'],'provenance':{'is_synthetic':True,'label':source['label'],'cutoff':source['cutoff'],'dataset_sha':source['batch']['dataset_sha'],'history_source':'assets/orders.json + 当月新增订单','forecast_source':'模拟时序模型HTTP API','analysis_source':'独立模拟大模型分析HTTP API'}}
    def step(k,title,status,detail):result['steps'].append({'id':k,'title':title,'status':status,'detail':detail})
    try:scope=resolve_scope(query,source,spec,customer,start_month,months)
    except (ValueError,TypeError) as e:
        result['message']=str(e);result['explanation']['headline']=str(e);step('scope','确认物料、客户与预测周期','error',str(e));return result
    specs=scope['specs'];customer=scope['customer'];start=scope['start_month'];months=scope['months'];end=add_month(start,months)
    end=(date.fromisoformat(end+'-01')-__import__('datetime').timedelta(days=1)).isoformat()
    result.update(scope=scope,spec=specs[0] if len(specs)==1 else '全部物料',material=source['materials'].get(specs[0],{}).get('material','待核对物料') if len(specs)==1 else '多物料分析',customer=customer,period={'key':'monthly','label':f'{start} 至 {end[:7]}（逐月）','start':start+'-01','end':end,'start_month':start,'months':months})
    step('scope','确认物料、客户与预测周期','completed',f"{', '.join(specs)} / {customer} / {start}起{months}个月")
    repo=HistoryRepository(source)
    try:
        for model in specs:
            raw=gateway.predict(model,customer,start,months,result['request_id']);forecast=validate_prediction(raw,model,customer,start,months)
            if forecast is not None and forecast['dataset_sha'] != source['batch']['dataset_sha']: raise GatewayError('预测使用的数据批次与本次查询不一致')
            step('forecast-'+model,'调用月度数量与价格预测','completed',model+('：返回逐月预测' if forecast is not None else '：返回数字0，不可预测'))
            history=repo.read([model],customer)
            state='predicted' if forecast is not None else 'unpredictable' if history['records'] else 'no_history'
            result['items'].append({'spec':model,'material':source['materials'].get(model,{}).get('material','新增物料'),'status':state,'unit':'件','currency':'CNY','history':history,'forecast':forecast,'reason':'模拟回测偏差较大，需要人工复核' if forecast and any(r.get('backtest_mape') is not None and r['backtest_mape']>.3 for r in forecast['monthly']) else '缺少足够重复历史' if state=='unpredictable' else '无历史样本，等待离线重新计算' if state=='no_history' else '返回可预测结果'})
        result['history']=repo.read(specs,customer);step('history','查询并汇总历史数量、价格与交付','completed',f"{result['history']['summary']['record_count']}笔，样本完整取回")
    except GatewayError as e:
        result.update(status='api_error',message=str(e));step('forecast','预测服务失败','error',str(e));result['items']=[];return result
    except (sqlite3.Error,ValueError,OSError,KeyError) as e:
        result.update(status='history_error',message='历史数据查询失败，不能当成无历史');step('history','查询失败','error',result['message']);return result
    states={x['status'] for x in result['items']};result['status']=next(iter(states)) if len(states)==1 else 'mixed'
    rows=[r for i in result['items'] if i['forecast'] for r in i['forecast']['monthly']]
    if rows:
        result['forecast']={'monthly':merge_months(rows),'summary':summarize_forecast(rows),'quality_notes':list(dict.fromkeys(n for i in result['items'] if i['forecast'] for n in i['forecast']['quality_notes'])),'model_version':rows[0]['model_version'],'dataset_sha':source['batch']['dataset_sha'],'input_order_ids':source['batch'].get('included_order_ids',[])}
    result['analytics']=build_analytics(result['history'],source,customer)
    if len(specs)>1: result['analytics']['price_trend']['comparison'] += '；多物料加权单价受采购结构影响，不代表同物料涨价。'
    by_material=[{'spec':i['spec'],'material':i['material'],'status':i['status'],'history_quantity':i['history']['summary']['total_quantity'],'forecast_quantity':i['forecast']['summary']['quantity'] if i['forecast'] else None,'forecast_amount':i['forecast']['summary']['amount'] if i['forecast'] else None} for i in result['items']]
    by_customer=[]
    for c in source['customers']:
        if customer!='all' and customer!=c:continue
        rs=[r for r in rows if r['customer']==c];s=summarize_forecast(rs)
        by_customer.append({'customer':c,'history_quantity':sum(r['quantity'] for r in result['history']['records'] if r['customer']==c),'forecast_quantity':s['quantity'] if rs else None,'forecast_amount':s['amount'] if rs else None,'unpredictable_items':[i['spec'] for i in result['items'] if i['forecast'] is None]})
    by_month=[]
    for offset in range(months):
        month=add_month(start,offset);rs=[r for r in rows if r['month']==month];s=summarize_forecast(rs);hm=add_month(month,-12)
        historical=next((r for r in result['history']['monthly'] if r['month']==hm),None)
        by_month.append({'month':month,'history_month':hm,'history_quantity':historical['quantity'] if historical else None,'forecast_quantity':s['quantity'] if rs else None,'forecast_unit_price':s['weighted_unit_price'] if rs else None,'forecast_amount':s['amount'] if rs else None})
    result['report_dimensions']={'by_material':by_material,'by_customer':by_customer,'by_month':by_month,'suggestions':[],'excluded_specs':[i['spec'] for i in result['items'] if i['forecast'] is None]}
    try:
        explanation=gateway.explain({k:result[k] for k in ['status','period','history','analytics','items']},result['request_id'])
        required=['headline','body','factors','limitations','influences','analysis_model','analysis_source_id','suggestions']
        if not isinstance(explanation,dict) or any(k not in explanation for k in required):raise GatewayError('分析服务输出不完整')
        refs={r['source_id'] for r in result['history']['records']}|{r['prediction_id'] for r in rows}|{x['id'] for x in result['analytics']['context']}|{'STAT-DELIVERY','STAT-CUSTOMER'}
        if any(ref not in refs for x in explanation['influences']+explanation['suggestions'] for ref in x.get('evidence_refs',[])):raise GatewayError('分析引用的证据不存在')
        for suggestion in explanation['suggestions']:
            original=[r for r in rows if r['spec']==suggestion['spec'] and r['customer']==suggestion['customer']]
            if suggestion['quantity']!=sum(r['quantity'] for r in original):raise GatewayError('分析服务更改了模型数量')
        result['report_dimensions']['suggestions']=explanation.pop('suggestions');result['explanation']=explanation
    except (GatewayError,KeyError,TypeError) as e:
        result.update(status='api_error',message='分析服务失败，未生成正式结论：'+str(e),forecast=None,report_dimensions=None);step('analysis','模拟分析服务','error',result['message']);return result
    step('analysis','结合订单、交付、客户、计划与市场形成说明','completed',explanation['analysis_source_id'])
    step('report','按物料、客户、时间组织可追溯报告','completed','直接引用同次月度结果，不另建预测计算')
    result['message']=explanation['headline'];return result
