"""Read-only order/date executor. Reminders produce review links; never write business state."""
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
import json,sys,re
ROOT=Path(__file__).resolve().parents[1]
D=json.loads((ROOT/'assets/orders.json').read_text())
TODAY=datetime.now(timezone(timedelta(hours=8))).date()
NODES={'payment':'付款截止','delivery':'计划交付','settlement':'结算'}
STATE=Path('scratch/order-assistant-context.json')

def safe(v):return str(v if v is not None else '—').replace('|','\\|').replace('\n',' ').replace('<','&lt;').replace('>','&gt;')
def money(v):return f'{v:,.2f}'
def delta(v,asof):return (date.fromisoformat(v)-asof).days if v else None
def days(v,asof):
 n=delta(v,asof);return '日期未提供' if n is None else '今天到期' if n==0 else f'还有{n}天' if n>0 else f'日期已过{-n}天'
def entities(o,node):return o['lines'] if node=='delivery' else o['invoices'] if node=='payment' else o['settlements']
def dates(o,node):return sorted(set(x.get('date' if node=='settlement' else 'due') for x in entities(o,node))- {None})
def table(headers,rows):return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(safe(v) for v in row)+' |' for row in rows)
def link(o,params=''):return '/workspace/c/new?module=order-tracking&order='+o['id']+params

def clear_context():
 STATE.parent.mkdir(exist_ok=True,parents=True)
 STATE.write_text('{}')  # Tombstone is mirrored; deleting a local file is not.

def execute(r):
 if not isinstance(r,dict):raise ValueError('请求必须是对象')
 allowed={'action','order','position','node','window','supplier','material','mode','as_of','limit','offset'}
 if set(r)-allowed:raise ValueError('不支持的查询字段')
 try:context=json.loads(STATE.read_text())
 except (OSError,ValueError):context={}
 action=r.get('action','help');asof=date.fromisoformat(r.get('as_of',TODAY.isoformat()))
 node=r.get('node','all');window=r.get('window','attention')
 if node not in {*NODES,'all'}:raise ValueError('请选择付款、交付或结算节点')
 if window not in {'all','attention','past','today','week','month','future','missing'}:raise ValueError('不支持的日期范围')
 limit=r.get('limit',12);offset=r.get('offset',0)
 if type(limit)!=int or type(offset)!=int or not 1<=limit<=30 or not 0<=offset<=500:raise ValueError('分页参数不正确')
 rows=[];selected=None
 position=r.get('position')
 if 'position' in r and (type(position)!=int or not 1<=position<=30 or r.get('order') or action not in {'detail','reminder'}):
  clear_context()
  raise ValueError('列表序号须为1—30，且不能与订单号同时提供；仅用于详情或提醒')
 if position is not None:
  visible=context.get('visible_orders')
  number=visible[position-1] if isinstance(visible,list) and position<=len(visible) else None
  candidates=[o for o in D['orders'] if o['number']==number]
  if len(candidates)!=1:
   clear_context()
   return result('当前没有可核对的该序号订单。请重新查询列表或提供完整订单号。','waiting','核对列表选择',asof)
  selected=candidates[0]
  STATE.parent.mkdir(exist_ok=True,parents=True)
  STATE.write_text(json.dumps({'order':selected['number'],'visible_orders':visible},ensure_ascii=False))
 elif r.get('order'):
  key=str(r['order']).strip().lower();candidates=[o for o in D['orders'] if key in (o['id'].lower(),o['number'].lower())]
  if not candidates:candidates=[o for o in D['orders'] if key in o['number'].lower()]
  if len(candidates)!=1:
   clear_context()  # An unresolved explicit switch must not reuse the prior order.
   return result('未找到唯一订单。请提供完整订单号。'+('\n\n'+table(['候选订单','供应商'],[(o['number'],o['supplier']) for o in candidates[:10]]) if candidates else ''),'waiting','核对订单身份',asof)
  selected=candidates[0]
  STATE.parent.mkdir(exist_ok=True,parents=True)
  STATE.write_text(json.dumps({'order':selected['number'],**({'reminder_node':context['reminder_node']} if context.get('order')==selected['number'] and context.get('reminder_node') in NODES else {})},ensure_ascii=False))
 elif action in {'detail','reminder'}:
  try:previous=json.loads(STATE.read_text()).get('order');selected=next((o for o in D['orders'] if o['number']==previous),None)
  except (OSError,ValueError):pass
  if not selected:
   clear_context()
   return result('请提供要查看或设置提醒的完整订单号；也可以在订单详情点击“询问AI”。','waiting','补充订单号',asof)
 os=[selected] if selected else D['orders']
 for k in ('supplier','material'):
  if r.get(k):
   key=str(r[k]).strip().lower()
   os=[o for o in os if key in (o['supplier'].lower() if k=='supplier' else ' '.join(l['material']+' '+l['part'] for l in o['lines']).lower())]
 if action=='help':return result('我可以帮你查看订单全景、按日期筛选关注清单，或生成待确认的提醒设置。\n\n- 查看订单DEMO-ORDER-001的物料、金额与日期。\n- 本周有哪些计划交付日期需要关注？\n- 将DEMO-ORDER-001的交付提醒改为7天后。\n\n提醒设置需打开页面核对后保存；我不会更改付款状态或发送消息。','done','说明可用操作',asof)
 if action=='reminder':
  if 'node' not in r and context.get('order')==selected['number'] and context.get('reminder_node') in NODES:node=context['reminder_node']
  if node=='all':return result('请明确要调整付款、交付还是结算提醒。','waiting','补充提醒节点',asof)
  mode=str(r.get('mode',''));labels={'7':'7天后提醒','30':'30天后提醒','off':'不再提醒','default':'按规则提醒'}
  if mode not in labels:return result('请选择7天后、30天后、不再提醒或按规则提醒。','waiting','补充提醒周期',asof)
  nextday=(asof+timedelta(days=int(mode))).isoformat() if mode.isdigit() else None
  STATE.parent.mkdir(exist_ok=True,parents=True)
  STATE.write_text(json.dumps({'order':selected['number'],'reminder_node':node,**({'visible_orders':context['visible_orders']} if not r.get('order') and isinstance(context.get('visible_orders'),list) else {})},ensure_ascii=False))
  text=f"### 待确认的提醒设置\n\n订单：{selected['number']}\n\n节点：{NODES[node]}日期\n\n提醒方式：{labels[mode]}"+(f'\n\n下一次展示日期：{nextday}' if nextday else '')+f"\n\n[核对并保存提醒]({link(selected,'&node='+node+'&mode='+mode)})\n\n此为待确认方案，尚未保存；打开设置后由你确认。订单日期与金额保持不变。"
  return result(text,'waiting','生成待确认提醒',asof,[selected['number']])
 if action=='detail':
  o=selected
  text=f"### {o['number']} · 订单全景\n\n供应商：{safe(o['supplier'])}　客户：{safe(o['customer'])}\n\n订单金额：{money(o['amount'])} {o['currency']}　采购明细：{len(o['lines'])}条\n\n"
  text+=table(['物料 / 件号','数量','单位','单价','明细金额','计划交付日期','剩余天数'],[(l['material']+' / '+l['part'],l['quantity'],l['unit'],money(l['price']),money(l['amount']),l['due'],days(l['due'],asof)) for l in o['lines']])
  for n in ('payment','settlement'):
   text+='\n\n#### '+NODES[n]+'日期\n\n'+(table(['单据号','金额','日期','剩余天数'],[(x['number'],money(x['invoiceAmount' if n=='payment' else 'amount']),x['due' if n=='payment' else 'date'],days(x['due' if n=='payment' else 'date'],asof)) for x in entities(o,n)]) if entities(o,n) else '暂未提供对应单据。')
  text+=f'\n\n[查看订单详情]({link(o)})'
  return result(text,'done','核对订单与关联单据',asof,[o['number']])
 if action not in {'overview','orders','alerts'}:raise ValueError('不支持的操作；可查询订单、日期关注清单或生成提醒方案')
 def matches(v):
  n=delta(v,asof)
  return True if window=='all' else n is None if window=='missing' else False if n is None else n<0 if window=='past' else n==0 if window=='today' else 0<=n<=7 if window=='week' else 0<=n<=30 if window=='month' else n>30 if window=='future' else n<=7
 for o in os:
  ns=list(NODES) if node=='all' else [node]
  hit=[(n,v) for n in ns for v in (dates(o,n) or [None]) if matches(v)]
  if action=='overview' or action=='orders' and window=='all' or hit:rows.append((o,hit))
 total=len(rows);rows=rows[offset:offset+limit]
 # A new displayed list owns its ordered positions; it cannot borrow an old focus.
 STATE.parent.mkdir(exist_ok=True,parents=True)
 STATE.write_text(json.dumps({'visible_orders':[o['number'] for o,_ in rows]},ensure_ascii=False))
 if action=='overview':
  text=f'### 订单概览\n\n共{len(os)}笔订单，{sum(len(o["lines"]) for o in os)}条采购明细，金额合计{money(sum(o["amount"] for o in os))} 人民币。\n\n'
 else:text='### 日期关注清单\n\n' if action=='alerts' else '### 订单查询\n\n'
 if not rows:return result(text+'当前条件下没有匹配记录。可调整日期范围、供应商或物料。','empty','核对筛选结果',asof)
 text+=f'匹配{total}笔，本页展示第{offset+1}—{offset+len(rows)}笔。\n\n'
 def fmt(o,n):
  ds=dates(o,n);return '；'.join(d+'（'+days(d,asof)+'）' for d in ds) if ds else '日期未提供'
 text+=table(['订单 / 供应商','物料 / 件号','订单金额','付款截止日','计划交付日期','结算日期'],[(f'[{o["number"]}]({link(o)}) / '+o['supplier'],o['lines'][0]['material']+' / '+o['lines'][0]['part']+(f' 等{len(o["lines"])}项' if len(o['lines'])>1 else ''),money(o['amount']),fmt(o,'payment'),fmt(o,'delivery'),fmt(o,'settlement')) for o,_ in rows])
 text+='\n\n日期已过只表示日历日期已过，不代表未付款、未交付或未到账。提醒是否展示以页面设置为准。'
 return result(text,'done','读取订单并筛选日期',asof,[o['number'] for o,_ in rows])

def result(text,status,step,asof,orders=None):
 process={'version':1,'mode':'execution_recap','scene':'orders','nodes':[{'title':'读取订单与关联单据','summary':f'按{asof.isoformat()}核对订单日期','status':'done','details':['同一订单数据集中的物料、发票和结算单据']},{'title':step,'summary':{'waiting':'需要你补充或确认后继续','empty':'当前条件没有匹配记录','done':'已完成本轮核对'}[status],'status':status,'details':orders or []}]}
 return {'answer':'```business-process\n'+json.dumps(process,ensure_ascii=False,separators=(',',':'))+'\n```\n\n'+text+f'\n\n截至：{asof.isoformat()}。','status':status,'orders':orders or [],'action_applied':False}

if __name__=='__main__':
 try:
  raw=sys.argv[1] if len(sys.argv)>1 else sys.stdin.read(64001)
  if len(raw)>64000:raise ValueError('请求过长')
  out=execute(json.loads(raw))
 except (ValueError,TypeError,KeyError) as e:
  out=result('未能完成本次查询：'+safe(e)+'。请调整条件后重试。','waiting','核对请求',TODAY)
 print(json.dumps(out,ensure_ascii=False))
