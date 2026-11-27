# coding: utf-8
"""Local monthly forecast simulation, no production credentials or writes."""
import argparse,json,mimetypes,os,re,sys,threading,urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'skill/procurement-forecast-fast/scripts'))
from engine import ForecastGateway
from store import MonthlyStore,TZ
from simulated_services import forecast_response
from workflow import Workflow,WorkflowError
from adapters import history_adapter_from_env
from native_bridge import NativeBridge,NativeBridgeError

def native_summary(value):
    """Keep the immutable receipt first and return facts useful for interpretation.

    Full records/monthly rows remain in the frozen workflow used by UI/reports.
    The platform can move large tool results to files; its preview must retain
    the complete receipt rather than truncating the execution identity.
    """
    receipt={k:value[k] for k in ('ok','run_id','action','action_sha256','skill_sha256','cli_sha256','state')}
    out={'receipt':receipt,'ok':value['ok'],'state':value['state']}
    if value['action']=='prepare':
        out=native_summary({**value,'action':'history'})
        out['receipt']=receipt
        out['receipt']['subactions']=[{k:r[k] for k in ('ok','action','action_sha256')} for r in value['subactions']]
    elif value['action']=='forecast':
        out['scope']=value['scope']
        out['predictions']={spec:({'status':'predicted','summary':p['summary'],'quality_notes':p['quality_notes'],'model_version':p['model_version'],'monthly_count':len(p['monthly'])} if p is not None else {'status':'unpredictable','api_return':0}) for spec,p in value['predictions'].items()}
    elif value['action']=='history':
        f=value['facts'];a=f['analytics']
        out['facts_ref']=value['facts_ref']
        out['facts']={k:f[k] for k in ('scope','status','period','unit','currency')}
        out['facts']['history']={'summary':f['history']['summary'],'window':f['history']['window'],'complete':f['history']['complete']}
        columns=list(f['history']['monthly'][0]) if f['history']['monthly'] else []
        out['facts']['history'].update(monthly_columns=columns,monthly=[[r[k] for k in columns] for r in f['history']['monthly']])
        if f['status'] in ('unpredictable','no_history'):
            out['facts']['history']['records']=f['history']['records'][:20]
            out['facts']['history']['records_shown']=min(20,len(f['history']['records']))
        out['facts']['forecast']=None if f['forecast'] is None else {'summary':f['forecast']['summary'],'monthly_columns':['month','quantity','weighted_unit_price','amount'],'monthly':[[m['month'],m['quantity'],m['unit_price'],m['amount']] for m in f['forecast']['monthly']],'quality_notes':f['forecast']['quality_notes']}
        out['facts']['analytics']={k:a[k] for k in ('quantity_trend','price_trend','customer_changes')}
        out['facts']['analytics']['context']=[{k:c[k] for k in ('id','type','date','detail','impact') if k in c} for c in a['context']]
        out['facts']['analytics']['delivery']={k:v for k,v in a['delivery'].items() if k!='monthly'}
        columns=list(a['delivery']['monthly'][0]) if a['delivery']['monthly'] else []
        out['facts']['analytics']['delivery'].update(monthly_columns=columns,monthly=[[r[k] for k in columns] for r in a['delivery']['monthly']])
        out['facts']['items']=[{'spec':i['spec'],'status':i['status'],'reason':i['reason'],'history_summary':{k:i['history']['summary'][k] for k in ('record_count','total_quantity','active_months','month_count')}} for i in f['items']]
        out['facts']['report_dimensions']={k:f['report_dimensions'][k] for k in ('by_material','by_customer','by_month','excluded_specs')}
        columns=list(f['report_dimensions']['by_month'][0]) if f['report_dimensions']['by_month'] else []
        out['facts']['report_dimensions'].update(by_month_columns=columns,by_month=[[r[k] for k in columns] for r in f['report_dimensions']['by_month']])
        out['facts']['monthly_dimension_count']=len(f['report_dimensions']['by_month'])
        out['analysis_checks']={'price_change_available':a['price_trend']['previous'] is not None and a['price_trend']['current'] is not None,'missing_price_instruction':'缺少价格观测时写无法计算，不能写零变化','api_zero_meaning':'拒绝预测，原因未披露；不等于需求零，历史稀疏仅为样本观察'}
        out['facts']['provenance']={k:v for k,v in f['provenance'].items() if k in ('history_mode','history_source','forecast_source','cutoff','execution')}
        out['suggestion_targets']=[{**t,'evidence_refs':t['evidence_refs'][:1]} for t in value['suggestion_targets']]
        selected={'STAT-QUANTITY','STAT-PRICE','STAT-DELIVERY','STAT-CUSTOMER'}|{c['id'] for c in a['context']}|{ref for t in out['suggestion_targets'] for ref in t['evidence_refs']}
        if f['status'] in ('unpredictable','no_history'):selected|={o['source_id'] for o in f['history']['records'][:20]}
        out['evidence_refs']=[ref for ref in value['evidence_refs'] if ref in selected]
        out['detail_note']='统计覆盖完整查询结果；逐月明细与完整订单保留在同次页面和报告中。'
    else:
        out.update({k:value[k] for k in ('facts_ref','final_sha256','reports')})
    return out

class App(ThreadingHTTPServer):
    daemon_threads=True;allow_reuse_address=True
    def __init__(self,address,runtime=None,forecast_base=None,auto_refresh=True,clock=None,check_interval=30,public_prefix=''):
        super().__init__(address,Handler)
        self.public_prefix=public_prefix.rstrip('/')
        if not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*',self.public_prefix):raise ValueError('无效公开路径前缀')
        self.runtime=Path(runtime or HERE/'runtime');self.runtime.mkdir(parents=True,exist_ok=True)
        self.public_assets={('/' if p.name=='index.html' else '/'+p.name):(p.read_bytes(),mimetypes.guess_type(str(p))[0] or 'application/octet-stream') for p in (HERE/'public').iterdir() if p.is_file()}
        self.report_cache={};self.events=[]
        self.store=MonthlyStore(HERE/'skill/procurement-forecast-fast/assets/orders.json',self.runtime)
        forecast_base=forecast_base or os.environ.get('FORECAST_API_BASE')
        self.forecast_mode='external_http' if forecast_base else 'mock_http'
        self.forecast_is_external=bool(forecast_base)
        self.gateway=ForecastGateway(forecast_base or f'http://127.0.0.1:{self.server_port}')
        self.history_adapter=history_adapter_from_env()
        self.native_tool_key=os.environ.get('FORECAST_NATIVE_TOOL_KEY','')
        self.native_model_id=os.environ.get('FORECAST_NATIVE_MODEL_ID','')
        platform_base = os.environ.get('FORECAST_PLATFORM_BASE', 'http://127.0.0.1:3008').rstrip('/')
        self.agent_base_url = os.environ.get('FORECAST_AGENT_BASE_URL', platform_base + '/workspace/procurement-forecast')
        self.native = NativeBridge(platform_base, timeout=2)
        self.workflow=Workflow(self)
        from completion import CompletionSupervisor
        self.completion=CompletionSupervisor(self)
        self.clock=clock or (lambda:datetime.now(TZ));self.trace_lock=threading.Lock();self.stop_event=threading.Event();self.check_interval=check_interval
        self.worker=None
        if auto_refresh:
            self.worker=threading.Thread(target=self._monthly_loop,daemon=True);self.worker.start()
    def _monthly_loop(self):
        while not self.stop_event.wait(.3 if not self.store.state['batches'] else self.check_interval):
            self.ensure_month()
    def ensure_month(self):
        moment=self.clock()
        return self.store.refresh(moment.strftime('%Y-%m'),forecast_response,moment.date().isoformat())
    def trace(self,event):
        with self.trace_lock:
            self.events.append(event);self.events=self.events[-1000:]
            temp=self.runtime/'events.tmp';temp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in self.events));temp.replace(self.runtime/'events.jsonl')
    def server_close(self):
        self.stop_event.set()
        if self.worker:self.worker.join(timeout=1)
        super().server_close()

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def send_bytes(self,data,mime,code=200,download=None):
        try:
            self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin');self.send_header('X-Frame-Options','SAMEORIGIN')
            if download:self.send_header('Content-Disposition',f'attachment; filename="{download}"')
            self.end_headers();self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
    def json(self,data,code=200):return self.send_bytes(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode(),'application/json; charset=utf-8',code)
    def do_GET(self):
        parsed=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(parsed.query)
        if parsed.path in self.server.public_assets:
            data,mime=self.server.public_assets[parsed.path];return self.send_bytes(data,mime+'; charset=utf-8')
        if parsed.path=='/api/health':return self.json({'ok':True,'version':'0.8.0','mode':'native_skill','forecast_adapter':self.server.forecast_mode,'history_adapter':type(self.server.history_adapter).__name__,'scheduler':'monthly_check_30_seconds'})
        run=re.fullmatch(r'/api/runs/([a-f0-9]{32})',parsed.path)
        if run:
            try:return self.json(self.server.workflow.get(run[1],self.headers.get('Authorization','').removeprefix('Bearer ')))
            except WorkflowError as e:return self.json({'ok':False,'error':{'message':str(e)}},e.status)
        if parsed.path=='/api/catalog':
            self.server.ensure_month();return self.json(self.server.store.catalog())
        if parsed.path=='/api/forecast':
            try:
                self.server.ensure_month();batch=self.server.store.catalog()['batch']
                value=forecast_response(q.get('spec',[''])[0],q.get('customer',['all'])[0],q.get('start_month',['2026-12'])[0],int(q.get('months',['12'])[0]),batch);code=200
            except RuntimeError:value={'ok':False,'error':{'message':'模拟预测服务HTTP503'}};code=503
            except (ValueError,KeyError,TypeError):value={'ok':False,'error':{'message':'无效月度参数'}};code=422
            self.server.trace({'type':'forecast_http','request_id':self.headers.get('X-Request-ID'),'status':code,'spec':q.get('spec',[''])[0]})
            return self.json(value,code)
        report=re.fullmatch(r'/api/reports/([a-f0-9]{32})/(report\.html|report\.md|result\.json)',parsed.path)
        if report:
            file=self.server.runtime/'reports'/report[1]/report[2]
            cached=self.server.report_cache.get((report[1],report[2]))
            if cached is not None or file.exists():return self.send_bytes(cached if cached is not None else file.read_bytes(),{'report.html':'text/html','report.md':'text/markdown','result.json':'application/json'}[report[2]]+'; charset=utf-8',download=report[2] if q.get('download')==['1'] else None)
            return self.json({'ok':False,'error':{'message':'报告不存在，请重新查询。'}},404)
        public=(HERE/'public').resolve();file=(public/(urllib.parse.unquote(parsed.path).lstrip('/') or 'index.html')).resolve()
        if file.is_relative_to(public) and file.is_file():return self.send_bytes(file.read_bytes(),(mimetypes.guess_type(str(file))[0] or 'application/octet-stream')+'; charset=utf-8')
        return self.json({'ok':False,'error':{'message':'资源不存在'}},404)
    def body(self):
        origin=self.headers.get('Origin')
        if origin and urllib.parse.urlsplit(origin).netloc!=self.headers.get('Host'):raise PermissionError('拒绝跨来源请求')
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<300_000:raise ValueError('请求体过大或为空')
        data=json.loads(self.rfile.read(size))
        if not isinstance(data,dict):raise ValueError('参数必须为对象')
        return data
    def do_POST(self):
        try:payload=self.body()
        except PermissionError as e:return self.json({'ok':False,'error':{'message':str(e)}},403)
        except (ValueError,UnicodeDecodeError):return self.json({'ok':False,'error':{'message':'无效JSON或参数'}},400)
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/skill-execute':
            try:
                if set(payload)!={'request_json'} or not isinstance(payload['request_json'],str):raise WorkflowError('原生工具参数必须为request_json字符串',400)
                tool_input=json.loads(payload['request_json'])
                if not isinstance(tool_input,dict) or set(tool_input)-{'run_id','token','action','explanation'}:raise WorkflowError('原生工具参数无效',400)
                runid=tool_input.get('run_id');token=tool_input.get('token');action=tool_input.get('action')
                if action not in ('prepare','forecast','history','finalize'):raise WorkflowError('不支持的原生工具动作',400)
                data=self.server.workflow._hashes()
                if action=='finalize':data['explanation']=tool_input.get('explanation')
                elif 'explanation' in tool_input:raise WorkflowError('只有finalize接受解释',400)
                value=self.server.workflow.prepare(runid,token,data) if action=='prepare' else self.server.workflow.action(runid,token,action,data)
                return self.json(native_summary(value))
            except (WorkflowError,ValueError,TypeError) as e:return self.json({'ok':False,'error':{'message':str(e) if isinstance(e,WorkflowError) else '无效工具JSON'}},getattr(e,'status',400))
        if path in ('/api/analyze','/api/explanation'):
            return self.json({'ok':False,'error':{'message':'此入口已停用，请通过平台任务模式加载采购需求预测Skill执行。'}},410)
        if path=='/api/runs':
            try:
                self.server.ensure_month();value=self.server.workflow.create(payload)
                value['agent_base_url']=self.server.agent_base_url
                value['native_tool_key']=self.server.native_tool_key
                value['native_model_id']=self.server.native_model_id
                return self.json(value,201)
            except WorkflowError as e:return self.json({'ok':False,'error':{'message':str(e)}},e.status)
        run=re.fullmatch(r'/api/runs/([a-f0-9]{32})/(forecast|history|finalize|verify|bind)',path)
        if run:
            token=self.headers.get('Authorization','').removeprefix('Bearer ')
            try:
                if run[2]=='bind':
                    return self.json(self.server.completion.bind(run[1],token,self.headers.get('Cookie',''),payload),202)
                if run[2]=='verify':
                    contract=self.server.workflow.verification_contract(run[1],token)
                    evidence=self.server.native.verify(self.headers.get('Cookie',''),payload.get('chat_id'),payload.get('session_version_id'),{'run_id':run[1],'native_tool_key':self.server.native_tool_key,**contract})
                    value=self.server.workflow.verify(run[1],token,evidence)
                else:value=self.server.workflow.action(run[1],token,run[2],payload)
                return self.json(value)
            except (WorkflowError,NativeBridgeError) as e:return self.json({'ok':False,'error':{'message':str(e)}},e.status_code)
        if path=='/api/monthly-refresh':
            batch=self.server.ensure_month();catalog=self.server.store.catalog();self.server.trace({'type':'monthly_refresh','version':batch['version'],'added':batch['added_count']})
            return self.json({'ok':True,'batch':batch,'recent_batches':catalog['recent_batches']})
        if path=='/api/recalculate':
            spec=payload.get('spec','')
            if not isinstance(spec,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._ ×/-]{1,79}',spec):return self.json({'ok':False,'error':{'message':'请提供有效型号'}},400)
            return self.json({'ok':True,'job':self.server.store.recalculate(spec.upper())})
        return self.json({'ok':False,'error':{'message':'接口不存在'}},404)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--runtime');parser.add_argument('--public-prefix',default='');args=parser.parse_args()
    app=App((args.host,args.port),runtime=args.runtime,public_prefix=args.public_prefix);print(f'场景二月度模拟 http://{args.host}:{app.server_port}',flush=True)
    try:app.serve_forever()
    except KeyboardInterrupt:pass
    finally:app.server_close()
