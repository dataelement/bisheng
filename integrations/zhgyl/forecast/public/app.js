'use strict';

const $ = id => document.getElementById(id);
const form = $('query-form');
const result = $('result');
const queryInput = $('query');
function updateQueryHint() {
  const filled=Boolean(queryInput.value.trim());
  $('natural-query-summary').textContent=filled?'草稿已就绪，确认后开始分析':'设置预测范围';
  $('clear-query-button').hidden=!filled;
}
queryInput.addEventListener('input',updateQueryHint);
$('clear-query-button').addEventListener('click',()=>{queryInput.value='';updateQueryHint();queryInput.focus();});
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const text = value => typeof value === 'string' || typeof value === 'number' ? String(value) : '';
const esc = value => escapeHTML(text(value) || '—');
const list = value => Array.isArray(value) ? value : [];
const num = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
const fmt = (value, digits = 2) => num(value) === null ? '—' : new Intl.NumberFormat('zh-CN', {maximumFractionDigits:digits}).format(Number(value));
const cash = value => num(value) === null ? '—' : `¥${new Intl.NumberFormat('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value))}`;
const percent = value => num(value) === null ? '不可比' : `${Number(value)>0?'+':''}${fmt(value,1)}%`;
const date = value => text(value).slice(0,10) || '—';
const statusLabels = {predicted:'已生成月度预测',mixed:'部分可预测',unpredictable:'暂不可预测',no_history:'暂无历史数据',needs_input:'需补充查询条件',api_error:'预测服务异常',history_error:'历史数据服务异常'};
const statusClass = status => ['api_error','history_error'].includes(status) ? 'error' : status === 'predicted' ? '' : 'warning';
const colors = {quantity:'#1577d8',unit_price:'#078a9d',delivery:'#188a87'};
let activeController = null;
let lastPayload = null;
let latestData = null;
let refreshing = false;
let catalogReady = false;
let refreshJobs = 0;
const jobs = new Map();

function setStatus(message, loading = false, quiet = false) {
  $('status').textContent = message;
  $('status').classList.toggle('loading', loading);
  $('status').classList.toggle('status-quiet', quiet);
}
function setBusy(busy) {
  form.setAttribute('aria-busy', String(busy));
  $('new-query-button').disabled = busy;
  form.querySelectorAll('input,select,button').forEach(control => { if (control.id !== 'cancel-button') control.disabled = busy; });
  document.querySelectorAll('.example').forEach(button => { button.disabled = busy; });
  $('cancel-button').hidden = !busy;
  $('analyze-button').querySelector('span').textContent = busy ? '正在分析' : '开始分析';
  $('refresh-button').disabled = busy || refreshing;
}
async function request(url, body, signal) {
  const response = await fetch(new URL(url.replace(/^\//, ''), document.baseURI), body === undefined ? {signal} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), signal});
  let data;
  try { data = await response.json(); } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('服务返回了无法读取的结果，请重试。');
  }
  if (!response.ok || data.ok === false) throw new Error(text(data.error?.message) || text(data.message) || '服务未能完成请求，请稍后重试。');
  return data;
}
function metric(label, value, unit, note, cls = '') {
  return `<div class="metric ${cls}"><div class="metric-label">${escapeHTML(label)}</div><div class="metric-value">${escapeHTML(value)}${unit?`<small>${escapeHTML(unit)}</small>`:''}</div><div class="metric-note">${escapeHTML(note)}</div></div>`;
}
function table(headers, rows, label, classes = []) {
  if (!rows.length) return '<div class="empty-inline">当前范围没有可展示的记录。</div>';
  return `<div class="table-scroll" role="region" tabindex="0" aria-label="${escapeHTML(label)}，可左右滚动"><table><thead><tr>${headers.map((head,i)=>`<th scope="col"${classes.includes(i)?' class="num"':''}>${escapeHTML(head)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map((cell,i)=>`<td${classes.includes(i)?' class="num"':''}>${escapeHTML(cell??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function refs(values) { return list(values).length ? `<div class="evidence-ref">证据引用：${list(values).map(esc).join(' · ')}</div>` : ''; }
function qualityNotes(data) {
  const notes = new Map();
  const addNote = (value, spec) => {
    const note = typeof value === 'string' ? value : text(value?.detail) || text(value?.message);
    if (!note) return;
    if (!notes.has(note)) notes.set(note, new Set());
    if (text(spec)) notes.get(note).add(text(spec));
  };
  list(data.forecast?.quality_notes).forEach(note=>addNote(note));
  list(data.items).forEach(item=>list(item.forecast?.quality_notes).forEach(note=>addNote(note,item.spec)));
  const merged = [...notes].map(([note,specs])=>`${note}${specs.size ? `（适用物料：${[...specs].join('、')}）` : ''}`);
  list(data.items).forEach(item => {
    const samples = [...new Set(list(item.forecast?.monthly).filter(row=>num(row.backtest_mape)!==null).map(row=>`${row.model_version} · ${row.is_synthetic?'模拟':'API返回'}回测 MAPE ${fmt(Number(row.backtest_mape)*100,1)}%`))];
    samples.forEach(sample=>merged.push(`${item.spec}：${sample}。指标口径及模拟标记以该条API原值为准，不代表已通过业务验收。`));
  });
  return [...new Set(merged)];
}
function modelQualityCard(data) {
  const rows=list(data.items).flatMap(item=>list(item.forecast?.monthly));
  if(!rows.length)return '';
  return `<details class="card"><summary class="model-summary">查看逐物料 / 客户预测原值与模型质量 · ${rows.length} 条</summary>${table(['月份','物料型号','客户','预测数量 / 件','单价 / CNY','预测金额 / CNY','模型版本','API回测 MAPE','置信度','预测来源 ID'],rows.map(row=>[row.month,row.spec,row.customer,fmt(row.quantity),cash(row.unit_price),cash(row.amount),row.model_version,num(row.backtest_mape)===null?'未提供':fmt(Number(row.backtest_mape)*100,1)+'%',row.confidence,row.prediction_id]),'逐物料客户预测与模型质量',[3,4,5,7])}<p class="model-foot">每条量价及质量指标均来自本次预测 API 原值；未返回的 MAPE 显示“未提供”，不补值。模拟标记和评测口径须按来源核对，不能据此认定已通过业务验收。</p></details>`;
}

/* Null observations split paths. Each forecast point comes directly from API monthly rows. */
function trendChart(historyRows, forecastRows, key, label, unit, fullHistory = false) {
  const allHist = list(historyRows).filter(row => text(row.month)).sort((a,b)=>text(a.month).localeCompare(text(b.month)));
  const hist = fullHistory ? allHist : allHist.slice(-12);
  const future = list(forecastRows).filter(row => text(row.month));
  const months = [...new Set([...hist,...future].map(row => row.month))].sort();
  const hMap = new Map(hist.map(row=>[row.month,row]));
  const fMap = new Map(future.map(row=>[row.month,row]));
  const valid = [...hist,...future].map(row=>num(row[key])).filter(value=>value!==null);
  if (!months.length || !valid.length) return `<div class="empty-state">暂无可展示的${escapeHTML(label)}数据。缺失单价保留为空，不以 0 绘制。</div>`;
  const w = Math.max(640,months.length*30), h = 280, left = 62, right = 24, top = 38, bottom = 43;
  const plotW = w-left-right, plotH = h-top-bottom;
  const min = Math.min(0,...valid), max = Math.max(...valid,1), span = max-min || 1;
  const step = plotW/Math.max(months.length,1);
  const x = index => left+step*(index+.5);
  const y = value => top+(max-value)/span*plotH;
  const color = colors[key] || colors.delivery;
  const gradientId = `chart-area-${key}`;
  let svg = `<defs><linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity=".24"/><stop offset="100%" stop-color="${color}" stop-opacity=".015"/></linearGradient><linearGradient id="${gradientId}-history" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#6e91ac" stop-opacity=".12"/><stop offset="100%" stop-color="#6e91ac" stop-opacity="0"/></linearGradient></defs>`;
  if (future.length) {
    const first = months.indexOf(future.map(row=>row.month).sort()[0]);
    const boundary = left+step*first;
    svg += `<rect x="${boundary}" y="${top-8}" width="${w-right-boundary}" height="${plotH+8}" rx="4" fill="${color}" opacity=".035"/><line x1="${boundary}" y1="${top-8}" x2="${boundary}" y2="${h-bottom}" stroke="${color}" stroke-opacity=".45" stroke-width="1" stroke-dasharray="3 5"/><circle cx="${boundary}" cy="16" r="3" fill="${color}"/><text x="${Math.min(boundary+9,w-118)}" y="20" class="forecast-label" style="fill:${color}">预测起点 ${escapeHTML(months[first])}</text>`;
  }
  [0,.25,.5,.75,1].forEach(fraction=>{
    const value=min+span*fraction, yy=y(value);
    svg += `<line x1="${left}" x2="${w-right}" y1="${yy}" y2="${yy}" stroke="#dce7ee" stroke-width="1" stroke-dasharray="3 5"/><text x="${left-12}" y="${yy+4}" text-anchor="end">${escapeHTML(fmt(value,max>100?0:1))}</text>`;
  });
  function series(map, forecast) {
    const segments=[]; let segment=[]; let dots='';
    months.forEach((month,index)=>{
      const value = num(map.get(month)?.[key]);
      if (value===null) { if(segment.length)segments.push(segment);segment=[];return; }
      segment.push([x(index),y(value)]);
      dots+=`<circle aria-label="${escapeHTML(month)} ${forecast?'模拟预测':'历史订单'} ${escapeHTML(label)} ${escapeHTML(String(value))} ${escapeHTML(unit)}" class="chart-point ${forecast?'forecast-point':''}" cx="${x(index)}" cy="${y(value)}" r="${months.length>30?2.5:3.5}" fill="white" stroke="${forecast?color:'#7895ae'}" stroke-width="2" tabindex="0"><title>${escapeHTML(month)} · ${forecast?'模拟预测':'历史订单'} · ${escapeHTML(label)} ${escapeHTML(String(value))} ${escapeHTML(unit)}</title></circle>`;
    });
    if(segment.length)segments.push(segment);
    const paths=segments.map(points=>{
      const line=points.map((point,index)=>`${index?'L':'M'}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(' ');
      const area=`${line} L${points[points.length-1][0]},${h-bottom} L${points[0][0]},${h-bottom} Z`;
      return `<path d="${area}" fill="url(#${gradientId}${forecast?'':'-history'})" stroke="none"/><path class="chart-series" d="${line}" fill="none" stroke="${forecast?color:'#7895ae'}" stroke-width="${forecast?'3':'2'}" stroke-linecap="round" stroke-linejoin="round"${forecast?' stroke-dasharray="6 5"':''}/>`;
    }).join('');
    return paths+dots;
  }
  svg+=series(hMap,false)+series(fMap,true);
  months.forEach((month,index)=>{
    if (months.length<=8 || index===0 || index===months.length-1 || (index%Math.ceil(months.length/7)===0 && months.length-1-index>=Math.ceil(months.length/7))) svg+=`<text x="${x(index)}" y="${h-15}" text-anchor="middle">${escapeHTML(month)}</text>`;
  });
  return `<div class="chart-container" data-chart-key="${escapeHTML(key)}"><div class="chart-toolbar"><span>${fullHistory?'完整历史':'近期历史（最多 12 个月）'}${future.length?' + 所选预测月份':''}</span>${allHist.length>12?`<button type="button" data-chart-history="${escapeHTML(key)}" aria-pressed="${fullHistory}">${fullHistory?'查看近期':'查看全部历史'}</button>`:''}<button type="button" data-zoom-chart aria-pressed="false">放大图表</button></div><div class="chart-scroll" tabindex="0" role="region" aria-label="${escapeHTML(label)}月度趋势，可左右滚动"><svg class="trend-chart" viewBox="0 0 ${w} ${h}" style="min-width:${fullHistory?Math.max(640,months.length*26):480}px;--chart-full-width:${w}px" role="img" aria-label="${escapeHTML(label)}月度趋势，实线为历史，虚线为模拟预测，单位${escapeHTML(unit)}"><title>${escapeHTML(label)}月度趋势；缺失值不连线。完整数值见月度明细。</title>${svg}</svg></div></div>`;
}
function trendCard(data,key,label,unit,trend) {
  const color=colors[key], isPrice=key==='unit_price';
  const hasForecast=['predicted','mixed'].includes(data.status) && list(data.forecast?.monthly).length>0;
  const headline=hasForecast?(isPrice?cash(data.forecast?.summary?.weighted_unit_price):fmt(data.forecast?.summary?.quantity)):'—';
  const icon=isPrice?'<path d="M12 3v18M17 7H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>':'<path d="M3 17l5-5 4 3 8-10M15 5h5v5"/>';
  return `<section class="card chart-card ${isPrice?'price-chart':'quantity-chart'}" style="--chart-color:${color}"><div class="card-heading"><div class="chart-title"><span class="chart-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></span><div><h3>${escapeHTML(label)}趋势</h3></div></div><span class="chart-unit">${escapeHTML(unit)}</span></div><p class="chart-comparison"><strong class="chart-history-change">历史${isPrice?'价格':'数量'}变化 ${escapeHTML(percent(trend?.change_pct))}</strong><span>${esc(trend?.comparison || '月度订单历史与所选未来月份')}</span></p><div class="legend"><span><i class="history-line"></i>历史订单</span>${hasForecast?`<span style="color:${color}"><i class="forecast-line"></i>模拟预测</span><span class="legend-period">着色区域为预测期</span>`:''}</div>${trendChart(data.history?.monthly,data.forecast?.monthly,key,label,unit)}<p class="chart-note">${hasForecast?(isPrice?'加权单价 = 预测金额 ÷ 预测数量。':'预测数量按所选月份汇总。'):'本次仅展示实际历史订单，不补填预测数值。'}可左右滑动；缺失值不绘制，悬停或聚焦曲线点可看原值；完整数值见月度明细。</p></section>`;
}
function monthlyTable(data) {
  const history=list(data.history?.monthly).map(row=>({...row,kind:'历史'})).sort((a,b)=>text(a.month).localeCompare(text(b.month)));
  const forecast=list(data.forecast?.monthly).map(row=>({...row,kind:'预测'})).sort((a,b)=>text(a.month).localeCompare(text(b.month)));
  function rowsTable(rows,label) {
    if(!rows.length)return '<div class="empty-inline">当前没有可展示的月度记录，未填充任何估算值。</div>';
    return `<div class="table-scroll" role="region" tabindex="0" aria-label="${escapeHTML(label)}，可左右滚动"><table><thead><tr><th scope="col">月份</th><th scope="col">数据类型</th><th scope="col" class="num">数量 / 件</th><th scope="col" class="num">单价 / CNY</th><th scope="col" class="num">金额 / CNY</th><th scope="col">订单数 / 模型版本</th></tr></thead><tbody>${rows.map(row=>`<tr${row.kind==='预测'?' class="row-forecast"':''}><td>${esc(row.month)}</td><td><span class="kind-label ${row.kind==='预测'?'forecast':''}">${row.kind==='预测'?'模拟预测':'历史订单'}</span></td><td class="num">${escapeHTML(fmt(row.quantity))}</td><td class="num">${escapeHTML(cash(row.unit_price))}</td><td class="num">${escapeHTML(cash(row.amount))}</td><td>${row.kind==='预测'?esc(row.model_version || data.forecast?.model_version):escapeHTML(fmt(row.orders,0))+' 笔'}</td></tr>`).join('')}</tbody></table></div>`;
  }
  return `<section class="card"><div class="table-heading card-heading"><div><h3>月度数量与价格明细</h3><p>下表展示所选全部未来月份；完整历史月度记录可展开。预测为服务逐月输出，汇总单价按金额 ÷ 数量计算，缺值显示 —。</p></div><span class="subtle-tag">预测 ${forecast.length} 月 / 历史 ${history.length} 月</span></div>${rowsTable(forecast,'月度预测数量与价格明细')}<details id="history-monthly-details" class="evidence-details"><summary>展开完整历史月度明细 · ${history.length} 个月</summary>${rowsTable(history,'完整历史月度数量与价格明细')}</details></section>`;
}
function deliveryCard(delivery) {
  const d=delivery||{};
  return `<section class="card card-pad"><div class="card-heading"><div><h3>交付周期分析</h3><p>基于当前范围订单的交付记录 · 天</p></div><span class="dot teal" aria-hidden="true"></span></div><div class="delivery-stats"><div><strong>${escapeHTML(fmt(d.avg_days,1))}<small>天</small></strong><span>平均交付周期</span></div><div><strong>${escapeHTML(fmt(d.completed_orders,0))}</strong><span>已完成订单</span></div><div><strong>${escapeHTML(fmt(d.open_orders,0))}</strong><span>未完成订单</span></div></div><p class="chart-note">最短 ${escapeHTML(fmt(d.min_days,1))} 天 / 最长 ${escapeHTML(fmt(d.max_days,1))} 天</p>${trendChart(list(d.monthly),[],'avg_days','平均交付周期','天')}<p class="chart-note">${esc(d.note || '仅展示可核验的交付周期记录。')}</p><details id="delivery-monthly-details" class="evidence-details"><summary>展开完整交付月度明细 · ${list(d.monthly).length} 个月</summary>${table(['月份','平均周期 / 天','订单数'],list(d.monthly).map(row=>[row.month,fmt(row.avg_days,1),fmt(row.orders,0)]),'月度交付周期',[1,2])}</details></section>`;
}
function customerCard(changes) {
  const rows=list(changes);
  const max=Math.max(1,...rows.flatMap(row=>[num(row.previous_quantity),num(row.current_quantity)]).filter(value=>value!==null));
  return `<section class="card card-pad"><div class="card-heading"><div><h3>客户需求变化</h3><p>从历史订单比较客户采购数量，辅助识别需求迁移</p></div><span class="dot amber" aria-hidden="true"></span></div><div class="legend amber-legend"><span><i style="opacity:.5"></i>前期数量</span><span><i></i>本期数量</span></div>${rows.length?`<div class="customer-bars">${rows.map(row=>`<div><div class="customer-row-head"><strong>${esc(row.customer)}</strong><span>${escapeHTML(percent(row.change_pct))}</span></div>${num(row.previous_quantity)!==null?`<div class="customer-bar-track"><div class="customer-bar" style="width:${Math.max(0,Number(row.previous_quantity))/max*100}%"></div></div>`:''}${num(row.current_quantity)!==null?`<div class="customer-bar-track"><div class="customer-bar current" style="width:${Math.max(0,Number(row.current_quantity))/max*100}%"></div></div>`:''}<div class="customer-row-note">前期 ${escapeHTML(fmt(row.previous_quantity))} 件 → 本期 ${escapeHTML(fmt(row.current_quantity))} 件 · ${esc(row.comparison)}</div></div>`).join('')}</div>`:'<div class="empty-state">当前范围没有可比较的客户需求记录。</div>'}</section>`;
}
function explanationCard(data) {
  const e=data.explanation||{};
  return `<section class="card card-pad"><div class="card-heading"><div><h3>需求判断与影响因素</h3><p>平台 Agent 依据本次工具事实生成解释；数量与金额保留预测接口原值</p></div></div><h4 class="analysis-headline">${esc(e.headline || data.message || '本次分析说明')}</h4><p class="analysis-body">${esc(e.body || data.message)}</p><p class="analysis-source">分析服务：${esc(e.analysis_model)} · 来源 ID：${esc(e.analysis_source_id)}</p>${list(e.factors).length?`<div class="factors">${e.factors.map(f=>`<div class="factor"><h4>${esc(f.title)}</h4><strong>${esc(f.value)}</strong><p>${esc(f.detail)}</p></div>`).join('')}</div>`:''}${list(e.influences).length?`<div class="influences">${e.influences.map(i=>`<div class="influence"><strong>${esc(i.title)}</strong>${esc(i.detail)}${refs(i.evidence_refs)}</div>`).join('')}</div>`:''}${list(e.limitations).length?`<div class="limits"><strong>使用限制</strong><ul>${e.limitations.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div>`:''}</section>`;
}
function contextCard(rows) {
  const typeLabel = type => ({current_orders:'当期订单',orders:'当期订单',order:'当期订单',current_order:'当期订单',project_plan:'项目计划',plan:'项目计划',market:'市场信息',market_info:'市场信息'}[type] || text(type));
  return `<section class="card card-pad"><div class="card-heading"><div><h3>业务上下文 · 订单 / 项目计划 / 市场</h3><p>全部为模拟证据；当期订单引用本次纳入的测试订单记录，请核对来源 ID</p></div></div>${list(rows).length?`<div class="context-grid">${rows.map(row=>`<article class="context-item ${text(row.type).includes('plan')?'plan':text(row.type).includes('market')?'market':''}"><div class="context-type">${esc(typeLabel(row.type))} · 模拟</div><h4>${esc(row.title)}</h4><p>${esc(row.detail)}</p>${row.impact?`<p class="context-impact">影响：${esc(row.impact)}</p>`:''}<div class="context-meta">${escapeHTML(date(row.date))} · ${esc(row.source)}<br>来源 ID：<span class="mono">${esc(row.id)}</span></div></article>`).join('')}</div>`:'<div class="empty-state">本次未返回业务上下文证据。</div>'}</section>`;
}
const dimensionConfig = {
  by_material:{label:'按物料',headers:['物料型号','物料名称','状态','历史数量 / 件','预测数量 / 件','预测金额 / CNY'],nums:[3,4,5],row:r=>[r.spec,r.material,statusLabels[r.status]||r.status,fmt(r.history_quantity),fmt(r.forecast_quantity),cash(r.forecast_amount)]},
  by_customer:{label:'按客户',headers:['客户','历史数量 / 件','预测数量 / 件','预测金额 / CNY','不可预测物料'],nums:[1,2,3],row:r=>[r.customer,fmt(r.history_quantity),fmt(r.forecast_quantity),cash(r.forecast_amount),Array.isArray(r.unpredictable_items)?r.unpredictable_items.join('、')||'无':fmt(r.unpredictable_items,0)]},
  by_month:{label:'按时间',headers:['预测月份','可比历史月份','上年同月数量 / 件','预测数量 / 件','预测单价 / CNY','预测金额 / CNY'],nums:[2,3,4,5],row:r=>[r.month,r.history_month||'无可比月份',fmt(r.history_quantity),fmt(r.forecast_quantity),cash(r.forecast_unit_price),cash(r.forecast_amount)]}
};
function dimensionCard(data) {
  const d=data.report_dimensions||{};
  return `<section class="card"><div class="table-heading card-heading"><div><h3>多维度采购报告</h3><p>物料与客户维度：历史为完整样本期，预测为所选未来期，不能直接作为同比。时间维度：历史为上年同月，无可比记录时留空。合计仅包含可预测部分。</p></div></div><div class="dimension-tabs" role="tablist" aria-label="报告维度">${Object.entries(dimensionConfig).map(([key,c],i)=>`<button type="button" role="tab" id="tab-${key}" aria-controls="panel-${key}" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-dimension="${key}">${c.label} <span>(${list(d[key]).length})</span></button>`).join('')}</div>${Object.entries(dimensionConfig).map(([key,c],i)=>`<div role="tabpanel" id="panel-${key}" aria-labelledby="tab-${key}" tabindex="0"${i?' hidden':''}>${table(c.headers,list(d[key]).map(c.row),c.label+'采购报告',c.nums)}</div>`).join('')}${list(d.excluded_specs).length?`<div class="dimension-foot">未纳入预测合计的物料：${d.excluded_specs.map(esc).join('、')}。不可预测项保留为缺失，不作为 0 加总。</div>`:''}</section>`;
}
function suggestionsCard(rows) {
  return `<section class="card card-pad"><div class="card-heading"><div><h3>预排合同量建议</h3><p>使用当前预测原值，结合可追溯证据形成采购参考；需人工复核后执行</p></div></div>${list(rows).length?`<div class="suggestion-list">${rows.map(row=>`<article class="suggestion"><div class="suggestion-top"><h4>${esc(row.spec)}</h4><strong>${escapeHTML(fmt(row.quantity))} <small>件</small></strong></div><div class="suggestion-meta">${esc(row.customer)} · ${esc(typeof row.period==='object'?row.period.label:row.period)}</div><p>${esc(row.reason)}</p>${list(row.evidence_refs).length?`<details class="suggestion-evidence"><summary>证据引用 · ${list(row.evidence_refs).length} 项</summary>${refs(row.evidence_refs)}</details>`:''}</article>`).join('')}</div>`:'<div class="empty-state">当前未形成预排合同量建议。等待足够数据后重新评估。</div>'}</section>`;
}
function recalcButton(spec) {
  if (!text(spec) || spec==='all') return '';
  const job=jobs.get(spec);
  return `<button type="button" class="secondary-button" data-recalculate="${escapeHTML(spec)}">${job?'查看待补数据任务':'申请补数据后重新计算'}</button><div class="job-status" data-job-status="${escapeHTML(spec)}" role="status" aria-live="polite">${job?escapeHTML(`任务 ${job.id} · ${job.status} · ${job.message||''}`):''}</div>`;
}
function portfolioCard(items) {
  if (list(items).length<2) return '';
  return `<section class="card card-pad"><div class="card-heading"><div><h3>物料预测覆盖情况</h3><p>每个物料独立保留状态；预测合计不代表不可预测物料没有需求</p></div></div><div class="portfolio">${items.map(item=>`<article class="portfolio-item"><div><h4>${esc(item.spec)}</h4><span class="status-pill ${statusClass(item.status)}">${esc(statusLabels[item.status]||item.status)}</span></div><p>${esc(item.material)} · 历史 ${escapeHTML(fmt(item.history?.summary?.record_count,0))} 笔 / 预测 ${escapeHTML(fmt(item.forecast?.summary?.quantity))} 件</p>${item.reason?`<p>${esc(item.reason)}</p>`:''}${item.status==='no_history'?recalcButton(item.spec):''}</article>`).join('')}</div></section>`;
}
function historyCard(history) {
  const rows=list(history?.records);
  const orders=new Set(rows.map(row=>text(row.order_id)).filter(Boolean)).size;
  const suppliers=new Set(rows.map(row=>text(row.supplier)).filter(Boolean)).size;
  return `<section class="card history-orders-card"><div class="table-heading card-heading"><div><h3>历史订单与证据明细</h3><p>命中 ${rows.length} 条历史明细 · ${orders} 张订单 · ${suppliers} 家供应商</p><p>${escapeHTML(date(history?.window?.start))} — ${escapeHTML(date(history?.window?.end))} · ${rows.length} 笔 · ${history?.complete===true?'当前查询范围记录完整':'完整性以服务返回为准'}</p></div></div>${table(['订单编号','日期','供应商','客户','数量 / 件','单价 / CNY','金额 / CNY','型号','交付周期 / 天','预计交付','实际交付','来源 ID'],rows.map(r=>[r.order_id,date(r.date),r.supplier,r.customer,fmt(r.quantity),cash(r.unit_price),cash(r.amount),r.spec,fmt(r.lead_days,1),date(r.expected_delivery_date),date(r.actual_delivery_date),r.source_id]),'历史订单与来源',[4,5,6,8])}</section>`;
}
function reportLink(url,label,download=false) {
  if (!text(url)) return '';
  try {
    const base=new URL('.',document.baseURI);
    const parsed=new URL(url,document.baseURI);
    if (parsed.origin!==base.origin || !['http:','https:'].includes(parsed.protocol)) return '';
    const prefix=base.pathname+'api/reports/';
    let relative;
    if (parsed.pathname.startsWith('/api/reports/')) relative=parsed.pathname.slice(1);
    else if (parsed.pathname.startsWith(prefix)) relative=parsed.pathname.slice(base.pathname.length);
    else return '';
    const resolved=new URL(relative+parsed.search,base);
    if (!resolved.pathname.startsWith(prefix)) return '';
    return `<a class="report-link" href="${escapeHTML(resolved.pathname+resolved.search)}" ${download?'download':'target="_blank" rel="noopener"'}>${escapeHTML(label)} <span aria-hidden="true">${download?'↓':'↗'}</span></a>`;
  } catch { return ''; }
}
function reportActions(data) {
  return `<div class="report-actions"><span>本次分析报告 <small>同一请求 · 可追溯</small></span><div class="reports" aria-label="分析报告">${reportLink(data.reports?.html_url,'预览完整报告')}${reportLink(data.reports?.markdown_url,'下载 Markdown',true)}${reportLink(data.reports?.json_url,'下载结果 JSON',true)}<button type="button" class="report-link replay-button" data-replay>重播动效 <span aria-hidden="true">↻</span></button></div></div>`;
}
function processCard(data) {
  return `<details class="process-card"><summary>执行记录 · 实际分析过程与服务调用 · ${list(data.steps).length} 步</summary><ol class="process-steps">${list(data.steps).map(step=>`<li><strong>${esc(step.title || step.name)}</strong><span class="process-state">${esc(({completed:'已完成',skipped:'已跳过',error:'失败',failed:'失败'})[step.status] || step.status)}</span><p>${esc(step.detail || step.message)}</p>${step.source_id?refs([step.source_id]):''}</li>`).join('')||'<li>服务未返回分析步骤。</li>'}</ol></details>`;
}
let reportObserver;
function animateReport() {
  reportObserver?.disconnect();
  const blocks=result.querySelectorAll('.forecast-hero,.no-prediction,.card,.evidence-group,.process-card,.report-actions');
  blocks.forEach((block,index)=>{
    block.classList.remove('is-visible');block.classList.add('report-reveal');
    block.style.setProperty('--reveal-delay',`${Math.min(index%3*55,110)}ms`);
  });
  void result.offsetWidth;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) {
    blocks.forEach(block=>block.classList.add('is-visible'));return;
  }
  reportObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{
    if(entry.isIntersecting){entry.target.classList.add('is-visible');reportObserver.unobserve(entry.target);}
  }),{threshold:0,rootMargin:'0px 0px -18px 0px'});
  blocks.forEach(block=>reportObserver.observe(block));
}

function sourceBlock(data) {
  const p=data.provenance||{};
  const sourceText = value => typeof value==='object' && value!==null ? Object.entries(value).map(([k,v])=>`${k}: ${typeof v==='object'?JSON.stringify(v):v}`).join(' · ') : text(value);
  return `<div class="source-block"><strong>来源与可追溯性 · ${esc(p.label || '模拟数据')}</strong><div class="source-grid"><div>历史来源：${esc(sourceText(p.history_source))}</div><div>预测来源：${esc(sourceText(p.forecast_source))}</div><div>分析来源：${esc(sourceText(p.analysis_source))}</div></div><div>历史截止：${esc(p.cutoff)} · 生成时间：${esc(data.generated_at)} · 请求 ID：${esc(data.request_id)}</div>${p.native_agent?.chat_id?`<div>执行：平台原生 Agent / Skill · <a href="/workspace/c/${encodeURIComponent(p.native_agent.chat_id)}" target="_blank" rel="noopener">查看原生任务记录</a> · 解释模型 ${esc(data.explanation?.analysis_model)}</div>`:''}<div>数据版本 SHA：<span class="mono">${esc(p.dataset_sha)}</span> · 月度批次：${esc(data.batch?.version)}</div></div>`;
}
function renderResult(data) {
  $('welcome').hidden=true;
  latestData=data;
  const validForecast=['predicted','mixed'].includes(data.status) && data.forecast && list(data.forecast.monthly).length>0;
  const s=data.forecast?.summary||{}, hs=data.history?.summary||{}, notes=qualityNotes(data);
  const scope=data.scope||{};
  const scopeSpecs=list(scope.specs).length?scope.specs.join('、'):text(data.spec)==='all'?'全部物料':text(data.spec)||'采购分析';
  const customer=scope.customer||data.customer||'全部客户';
  const start=scope.start_month||data.period?.start_month||date(data.period?.start).slice(0,7);
  const months=scope.months||data.period?.months;
  const scopeText=`${customer==='all'?'全部客户':customer} · ${start} 起 ${months?`${months} 个月`:text(data.period?.label)} · ${date(data.period?.start)} — ${date(data.period?.end)}`;
  const errorStatus=['api_error','history_error'].includes(data.status);
  const unavailableTitle=data.status==='unpredictable'?'本次暂不可预测，已转历史订单查询':data.status==='no_history'?'当前查询范围暂无历史样本':data.explanation?.headline || data.message || '本次未生成预测';
  const unavailableBody=data.status==='unpredictable'?'预测 API 返回不可预测标记。下方展示历史依据，预测量价保留为空；完整分析见“需求判断、影响因素与业务证据”。':data.status==='no_history'?'当前没有可供分析的历史记录。补充历史样本后再评估，不补造预测。':data.message;
  const unavailable=!validForecast?`<div class="no-prediction"><h3>${esc(unavailableTitle)}</h3><p class="unavailable-reason">${esc(unavailableBody)}</p>${data.status==='no_history'?recalcButton(data.spec):''}${errorStatus?'<button type="button" class="secondary-button" data-retry>重新分析</button>':''}</div>`:'';
  const coverageItems=list(data.items),covered=coverageItems.filter(item=>item.status==='predicted').length;
  const coverage=data.status==='mixed'?(coverageItems.length?`仅覆盖 ${covered}/${coverageItems.length} 个可预测物料；`:'仅包含可预测物料；'):'';
  const conclusion=validForecast?`${coverage}未来${months?` ${months} 个月`:text(data.period?.label)}预测 ${fmt(s.quantity)} 件，参考金额 ${cash(s.amount)} CNY；需与客户实际订单核实。`:(data.message || data.explanation?.headline || statusLabels[data.status] || '本次分析说明');
  const limitations=list(data.explanation?.limitations);
  // Match the service's existing >30% simulated backtest warning; do not hide critical quality notes.
  const highBiasSpecs=coverageItems.filter(item=>list(item.forecast?.monthly).some(row=>num(row.backtest_mape)!==null&&Number(row.backtest_mape)>.3)).map(item=>text(item.spec));
  const importantNotes=notes.filter(note=>/偏差较大|高偏差|不足|稀疏|缺少|异常|失败|不可预测|无历史/.test(note)||highBiasSpecs.some(spec=>note.startsWith(spec+':')||note.startsWith(spec+'：')));
  const usageDetails=`<details class="usage-details"><summary>查看完整使用限制与模拟质量说明</summary><div>${limitations.length?`<strong>使用限制</strong><ul>${limitations.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}${notes.length?`<strong>模型质量与使用注意</strong><ul>${notes.map(note=>`<li>${escapeHTML(note)}</li>`).join('')}</ul>`:''}<p>当前业务数据与预测 API 为模拟，解释来自已核验的平台 Agent / Skill；专用历史 NL2SQL 待接入，采购需人工复核。月度量价来自预测服务，合计仅包含可预测部分。</p></div></details>`;
  const historyScope=`${scopeSpecs} · ${customer==='all'?'全部客户':customer} · ${date(data.history?.window?.start)} — ${date(data.history?.window?.end)}`;
  const metrics=validForecast?`<div class="metrics">${metric('所选周期 · 预测数量',fmt(s.quantity),'件','所选月份合计，仅包含可预测物料')}${metric('所选周期 · 预测金额',cash(s.amount),'','CNY · 逐月预测金额合计')}${metric('预测加权单价',cash(s.weighted_unit_price),'/ 件','金额 ÷ 数量；数量为零时单价为空','price')}${metric('历史订单 / 总数量',fmt(hs.record_count,0),'笔',`${fmt(hs.total_quantity)} 件 · ${fmt(hs.active_months,0)} 个活跃月`)}</div>`:'';
  const historySummary=!validForecast?`<div class="history-query-scope"><strong>${data.history?'已转历史订单查询':'本次尚无历史查询结果'}</strong><p>生效条件：${escapeHTML(historyScope)}</p><div class="history-hit-summary"><span>历史明细 <b>${escapeHTML(fmt(hs.record_count,0))}</b> 笔</span><span>历史总量 <b>${escapeHTML(fmt(hs.total_quantity))}</b> 件</span><span>需求活跃 <b>${escapeHTML(fmt(hs.active_months,0))}</b> / ${escapeHTML(fmt(hs.month_count,0))} 个月</span><span>历史加权单价 <b>${escapeHTML(cash(hs.avg_unit_price))}</b> / 件</span></div><small>来源：模拟历史订单 · 不生成或补填预测数据</small></div>`:'';
  result.innerHTML=`<section class="forecast-hero ${validForecast?'':'history-hero'}"><div class="result-heading"><div><h2 id="result-title" tabindex="-1">${escapeHTML(scopeSpecs)}</h2><div class="result-material">${esc(data.material)}</div><div class="result-meta"><span>本次预测请求</span>${escapeHTML(scopeText)}</div></div><span class="status-pill ${statusClass(data.status)}">${esc(statusLabels[data.status]||data.status)}</span></div>${validForecast?`<div class="decision-summary"><p>${escapeHTML(conclusion)}</p></div>`:unavailable}${historySummary}${metrics}<div class="synthetic-banner">模拟演示，仅供流程验证；采购需人工复核${validForecast?'，合计仅含可预测部分':''}。</div>${importantNotes.length?`<div class="quality-note"><strong>重要提示</strong><ul>${importantNotes.map(note=>`<li>${escapeHTML(note)}</li>`).join('')}</ul></div>`:''}${usageDetails}</section>${reportActions(data)}${processCard(data)}${!validForecast?historyCard(data.history):''}<div class="trend-grid">${trendCard(data,'quantity','采购数量','件',data.analytics?.quantity_trend)}${trendCard(data,'unit_price','采购单价','CNY / 件',data.analytics?.price_trend)}</div>${dimensionCard(data)}${suggestionsCard(data.report_dimensions?.suggestions)}<div class="two-column">${deliveryCard(data.analytics?.delivery)}${customerCard(data.analytics?.customer_changes)}</div><details class="evidence-group"><summary>月度数量与价格明细</summary>${monthlyTable(data)}</details><details class="evidence-group"><summary>需求判断、影响因素与业务证据</summary>${explanationCard(data)}${contextCard(data.analytics?.context)}${portfolioCard(data.items)}</details>${modelQualityCard(data)}${validForecast?`<details class="evidence-group"><summary>历史订单与证据明细 · ${list(data.history?.records).length} 笔</summary>${historyCard(data.history)}</details>`:''}<details class="evidence-group"><summary>来源与可追溯性</summary>${sourceBlock(data)}</details>`;
  result.hidden=false;
  document.body.classList.add('has-result');
  animateReport();
  setStatus(`${statusLabels[data.status]||'分析已返回'}。实际范围：${scopeText}。`,false,!errorStatus);
  $('result-title')?.focus({preventScroll:true});
}
function showRequestError(message) {
  latestData=null;
  result.innerHTML=`<div class="error-panel"><h2 tabindex="-1" id="result-title">分析未完成</h2><p>${escapeHTML(message)} 本次未生成已核验报告，查询条件已保留。</p><button class="secondary-button" type="button" data-retry>重试本次查询</button></div>`;
  result.hidden=false;
  setStatus('分析未完成，请检查服务或重试。');
  $('result-title')?.focus({preventScroll:true});
}
function currentPayload() { return {query:queryInput.value.trim(),spec:$('spec').value || 'all',customer:$('customer').value,start_month:$('start-month').value,months:Number($('months').value)}; }
async function analyze(payload) {
  if (activeController) return;
  const startedAt=performance.now();
  lastPayload={...payload};
  const controller=new AbortController(); activeController=controller;
  let timedOut=false,task=null;
  const timeout=setTimeout(()=>{timedOut=true;controller.abort();},30000);
  latestData=null; result.hidden=true;result.replaceChildren();$('welcome').hidden=true;
  document.body.classList.add('has-result');
  setBusy(true);setStatus('已提交查询，正在等待分析服务返回。可随时取消。',true);
  try {
    const data=await window.runForecastSkill(payload,{signal:controller.signal,onProgress:message=>setStatus(message,true),onTask:value=>{task=value;}});
    if (typeof data.status!=='string') throw new Error('分析响应缺少状态，无法安全展示预测。');
    renderResult(data);
    const completeSeconds=((performance.now()-startedAt)/1000).toFixed(1);
    setStatus(`${statusLabels[data.status]||'报告已生成'} · 本次用时 ${completeSeconds} 秒。`,false,false);
  } catch(error) {
    if (error.name==='AbortError'&&!timedOut) {
      let stopped=false;if(task)try{await window.stopForecastTask(task);stopped=true;}catch{}
      result.hidden=true;$('welcome').hidden=false;document.body.classList.remove('has-result');
      setStatus(stopped?'已终止平台任务，查询条件已保留。':task?'已停止页面等待，平台终止尚未确认，请核对任务记录。':'已停止提交等待；如平台已创建任务，请在任务记录中核对。');
    }
    else showRequestError(timedOut?'分析超过30秒预算，已停止本次任务。请检查模型服务状态后重试。':error.message||'网络连接暂不可用。');
  } finally { if(timedOut&&task)try{await window.stopForecastTask(task);}catch{} clearTimeout(timeout);if(activeController===controller){activeController=null;setBusy(false);} }
}

function renderBatch(batch, recents) {
  const b=batch||{};
  $('batch-summary').innerHTML=`<strong>${esc(b.month)} · ${esc(b.version)}</strong><br>纳入 ${escapeHTML(fmt(b.added_count,0))} 笔新增订单 · 数据集 ${escapeHTML(fmt(b.dataset_rows,0))} 笔<br>更新时间 ${esc(b.generated_at)} · 下次 ${esc(b.next_run)}`;
  $('batch-details').innerHTML=`<div>当前批次新增订单 ID：</div><div class="batch-orders">${list(b.order_ids).map(esc).join(' · ')||'本批次未新增订单'}</div><div class="chart-note">数据 SHA：${esc(b.dataset_sha)}</div><ul>${list(recents).map(item=>`<li><strong>${esc(item.month)} / ${esc(item.version)}</strong> · ${esc(item.generated_at)} · 新增 ${escapeHTML(fmt(item.added_count,0))} 笔<div class="batch-orders">${list(item.order_ids).map(esc).join(' · ')}</div></li>`).join('')||'<li>暂无最近更新记录。</li>'}</ul>`;
}
async function loadCatalog(preserve=true) {
  const data=await request('/api/catalog');
  const previousSpec=$('spec').value,previousCustomer=$('customer').value;
  $('spec').replaceChildren();
  const addOption=(select,value,label)=>{const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);};
  addOption($('spec'),'','请选择型号（可选）');
  addOption($('spec'),'all','全部物料');
  list(data.specs).forEach(item=>addOption($('spec'),text(item.spec),`${text(item.spec)} · ${text(item.material)}`));
  if (previousSpec && !$('spec').querySelector(`option[value="${CSS.escape(previousSpec)}"]`)) addOption($('spec'),previousSpec,`${previousSpec} · 自定义型号`);
  $('spec').value=previousSpec;
  $('customer').replaceChildren();addOption($('customer'),'all','全部客户');
  list(data.customers).forEach(customer=>addOption($('customer'),text(customer),text(customer)));
  if(previousCustomer && ![...$('customer').options].some(option=>option.value===previousCustomer))addOption($('customer'),previousCustomer,previousCustomer);
  $('customer').value=previousCustomer||'all';
  if (!catalogReady) { if(!editedFields.has('start-month'))$('start-month').value=data.default_start||'2026-12';if(!editedFields.has('months'))$('months').value=String(data.default_months||12); }
  catalogReady=true;renderBatch(data.batch,data.recent_batches);return data;
}
async function refreshMonthly() {
  if (refreshing||activeController) return;
  refreshing=true;$('refresh-button').disabled=true;$('refresh-button').textContent='正在刷新…';
  $('batch-status').textContent='正在纳入本月新增模拟订单并重算逐月预测快照…';
  const jobNumber=++refreshJobs;
  try {
    const data=await request('/api/monthly-refresh',{});
    renderBatch(data.batch,data.recent_batches);
    await loadCatalog(true);
    const b=data.batch||{};
    $('batch-status').textContent=`刷新完成：${text(b.version)}，本批次纳入 ${fmt(b.added_count,0)} 笔订单。相同月份与数据重复刷新不重复新增。${lastPayload?'正在用原查询范围重新分析，核对新订单变化。':''}`;
    if(lastPayload&&jobNumber===refreshJobs) {
      await analyze({...lastPayload});
      $('batch-status').textContent=`刷新完成：${text(b.version)}，本批次纳入 ${fmt(b.added_count,0)} 笔订单。相同月份与数据重复刷新不重复新增。${latestData?'已按原查询范围重新分析，请核对当前结果与订单明细。':'原查询未完成，可点击开始预测重试。'}`;
    }
  } catch(error) { $('batch-status').textContent=`月度刷新失败：${error.message}。可重新点击刷新。`; }
  finally { refreshing=false;$('refresh-button').disabled=Boolean(activeController);$('refresh-button').textContent='刷新月度数据'; }
}
async function recalculate(spec, button) {
  if(!spec)return;
  const status=result.querySelector(`[data-job-status="${CSS.escape(spec)}"]`);
  const existing=jobs.get(spec);
  if(existing){if(status)status.textContent=`任务 ${existing.id} · ${existing.status} · ${existing.message||''}`;return;}
  button.disabled=true;if(status)status.textContent='正在登记离线重新计算任务…';
  try {
    const data=await request('/api/recalculate',{spec});
    if(!data.job)throw new Error('服务未返回任务信息。');
    jobs.set(spec,data.job);button.textContent='查看待补数据任务';
    if(status)status.textContent=`任务 ${data.job.id} · ${data.job.status} · ${data.job.message||'等待补充历史样本后离线重新计算，当前不会生成预测。'}`;
  }catch(error){if(status)status.textContent=`登记失败：${error.message}，请重试。`;}
  finally{button.disabled=false;}
}
function selectDimension(key,focus=false) {
  if(!dimensionConfig[key])return;
  result.querySelectorAll('[data-dimension]').forEach(button=>{const selected=button.dataset.dimension===key;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;if(selected&&focus)button.focus();});
  Object.keys(dimensionConfig).forEach(name=>{const panel=$(`panel-${name}`);if(panel)panel.hidden=name!==key;});
}
result.addEventListener('click',event=>{
  if(event.target.closest('[data-replay]')){animateReport();return;}
  const historyToggle=event.target.closest('[data-chart-history]');
  if(historyToggle&&latestData){
    const key=historyToggle.dataset.chartHistory,full=historyToggle.getAttribute('aria-pressed')!=='true';
    const isDelivery=key==='avg_days',isPrice=key==='unit_price';
    const history=isDelivery?latestData.analytics?.delivery?.monthly:latestData.history?.monthly;
    const forecast=isDelivery?[]:latestData.forecast?.monthly;
    const label=isDelivery?'平均交付周期':isPrice?'采购单价':'采购数量',unit=isDelivery?'天':isPrice?'CNY / 件':'件';
    historyToggle.closest('.chart-container').outerHTML=trendChart(history,forecast,key,label,unit,full);
    result.querySelector(`[data-chart-history="${key}"]`)?.focus({preventScroll:true});return;
  }
  const zoom=event.target.closest('[data-zoom-chart]');if(zoom){const area=zoom.closest('.chart-container');const large=area.classList.toggle('chart-zoomed');zoom.setAttribute('aria-pressed',String(large));zoom.textContent=large?'恢复全景':'放大图表';return;}
  const retry=event.target.closest('[data-retry]');if(retry&&lastPayload){analyze({...lastPayload});return;}
  const tab=event.target.closest('[data-dimension]');if(tab){selectDimension(tab.dataset.dimension);return;}
  const recalc=event.target.closest('[data-recalculate]');if(recalc)recalculate(recalc.dataset.recalculate,recalc);
});
result.addEventListener('keydown',event=>{
  const tab=event.target.closest('[data-dimension]');if(!tab)return;
  const keys=Object.keys(dimensionConfig),index=keys.indexOf(tab.dataset.dimension);
  let next=null;if(event.key==='ArrowRight')next=keys[(index+1)%keys.length];if(event.key==='ArrowLeft')next=keys[(index+keys.length-1)%keys.length];if(event.key==='Home')next=keys[0];if(event.key==='End')next=keys[keys.length-1];
  if(next){event.preventDefault();selectDimension(next,true);}
});
const editedFields=new Set();
form.querySelectorAll('input,select').forEach(field=>{
  const markEdited=()=>editedFields.add(field.id);
  field.addEventListener('input',markEdited);field.addEventListener('change',markEdited);
});
form.addEventListener('submit',event=>{
  event.preventDefault();if(!form.reportValidity())return;
  if(!queryInput.value.trim()&&!$('spec').value){setStatus('请先输入物料型号或描述采购问题，也可以在可选条件中明确选择型号。');queryInput.focus();return;}
  analyze(currentPayload());
});
$('new-query-button').addEventListener('click',()=>{
  if(activeController)return;
  reportObserver?.disconnect();latestData=null;lastPayload=null;result.hidden=true;result.replaceChildren();
  $('welcome').hidden=false;document.body.classList.remove('has-result');queryInput.value='';$('spec').value='';
  updateQueryHint();setStatus('');queryInput.focus();window.scrollTo({top:0,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
});
$('cancel-button').addEventListener('click',()=>activeController?.abort());
$('refresh-button').addEventListener('click',refreshMonthly);
const samples=[
  {label:'查看月度采购量与价格',description:'有预测结果 · 查看量价趋势与备货建议',spec:'189A1002-1',query:'189A1002-1 从2026年12月起三个月的采购量和价格？',icon:'trend'},
  {label:'数据不足时，先核对历史',description:'暂不可预测 · 查看原因与完整历史订单',spec:'BACB30YP8K9',query:'BACB30YP8K9 采购需求分析',icon:'history'},
  {label:'高偏差模型',spec:'186A3107-751',query:'186A3107-751 采购需求分析'},
  {label:'多维汇总',spec:'all',display:'全部物料',query:'全部物料采购需求分析'},
  {label:'新型号',spec:'NEW-PART-001',query:'NEW-PART-001 采购需求分析'}
];
for(const [index,sample] of samples.entries()){
  const button=document.createElement('button');button.type='button';button.className=`example${index<2?' primary-example':''}`;
  if(index<2){
    const icon=sample.icon==='trend'?'<path d="M4 18V5m0 13h16M7 13l4-4 4 2 5-6m-5 0h5v5"/>':'<path d="M5 8a8 8 0 1 1-1 7M5 3v5H0m12-2v6l4 2"/>';
    button.innerHTML=`<span class="example-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${icon}</svg></span><span class="example-copy"><strong>${escapeHTML(sample.label)}</strong><span class="example-description">${escapeHTML(sample.description)}</span><code>${escapeHTML(sample.spec)}</code></span><span class="example-arrow" aria-hidden="true">↗</span>`;
  }else{
    const label=document.createElement('small');label.textContent=sample.label;
    const code=document.createElement('span');code.textContent=sample.display||sample.spec;button.append(label,code);
  }
  button.title=`填入${sample.label}示例；确认后才开始分析`;
  button.addEventListener('click',()=>{
    if(![...$('spec').options].some(option=>option.value===sample.spec)){const option=document.createElement('option');option.value=sample.spec;option.textContent=`${sample.spec} · 自定义型号`;$('spec').append(option);}
    $('spec').value=sample.spec;queryInput.value=sample.query;updateQueryHint();queryInput.focus();setStatus(`已填入${sample.spec}草稿，请确认条件后开始分析。`);
  });$(index<2?'primary-examples':'examples').append(button);
}
const catalogPromise=loadCatalog(false).catch(error=>{
  $('batch-summary').textContent='当前批次暂不可用。';
  $('batch-status').textContent=`目录读取失败：${error.message}。可点击刷新月度数据重试。`;
  setStatus('物料与客户目录未加载；可保留示例查询重试，或刷新月度数据重新读取。');
});

// Read-only presentation entry point for the D workspace; does not call analysis.
window.ForecastView=Object.freeze({showResult:renderResult,ready:catalogPromise});

// All entry URLs, including legacy ?demo=1, wait for an explicit user submission.
