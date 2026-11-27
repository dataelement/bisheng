"""Deterministic inquiry matching, following the reviewed transport flowchart.

The exact history API supplies a route pool. Never use associated-only bill rows
as candidates, never restart a narrowing step from the original pool.
"""
from decimal import Decimal
import re
import unicodedata

from contract import active_query, ContractError, encode, matches, norm, number, query, require

STRATEGY = 'transport-flowchart301-v3-gross-weight'
REQUIRED = {'origin','destination','model','gross_weight_kg','length_cm','width_cm','height_cm','dangerous_goods'}
OPTIONAL = {'mode','carrier','currency','date_from','date_to','date_field'}
CANONICAL = REQUIRED | OPTIONAL
RAW_FIELDS = {'gross_weight','packaging','net_weight','net_weight_kg','package_count'}
WEIGHT_UNITS = {'kg':'1','kgs':'1','千克':'1','公斤':'1','g':'0.001','克':'0.001',
                't':'1000','吨':'1000','lb':'0.45359237','lbs':'0.45359237','磅':'0.45359237'}
DIMENSION_UNITS = {'cm':'1','厘米':'1','mm':'0.1','毫米':'0.1','m':'100','米':'100',
                   'in':'2.54','inch':'2.54','inches':'2.54','英寸':'2.54'}
LABELS = {'origin':'起运地点','destination':'目的地点','model':'规格型号','gross_weight_kg':'毛重及单位',
          'length_cm':'包装长、宽、高及单位','width_cm':'包装长、宽、高及单位',
          'height_cm':'包装长、宽、高及单位','dangerous_goods':'危化品属性'}


def scalar(value):
    value = number(str(value))
    require(value > 0, 'Physical values must be positive')
    return int(value) if value == value.to_integral_value() else float(value)


def convert(value, unit, units):
    require(isinstance(unit,str) and norm(unit) in units, 'Unknown measurement unit')
    return scalar(number(value)*Decimal(units[norm(unit)]))


def prepare(raw):
    """Return a ready canonical target or bounded clarification, never guesses."""
    require(isinstance(raw,dict) and len(encode(raw)) <= 16384 and not set(raw)-CANONICAL-RAW_FIELDS,
            'Unknown inquiry field')
    target={k:v for k,v in raw.items() if k in CANONICAL and v not in (None,'')}
    problems=[]
    if 'gross_weight' in raw:
        require('gross_weight_kg' not in raw, 'Conflicting weight representations')
        value=raw['gross_weight']
        require(isinstance(value,dict) and set(value)=={'value','unit'}, 'Expected weight value/unit')
        try:
            target['gross_weight_kg']=convert(value['value'],value['unit'],WEIGHT_UNITS)
        except ContractError:
            problems.append('请明确有效毛重及支持的重量单位。')
    if 'packaging' in raw:
        require(not {'length_cm','width_cm','height_cm'} & set(raw), 'Conflicting packaging representations')
        value=raw['packaging']
        require(isinstance(value,dict) and not set(value)-{'length','width','height','unit','count'}, 'Unknown packaging field')
        if not {'length','width','height','unit'} <= set(value):
            problems.append('请补充包装长、宽、高和尺寸单位。')
        else:
            try:
                for axis in ['length','width','height']:
                    target[axis+'_cm']=convert(value[axis],value['unit'],DIMENSION_UNITS)
            except ContractError:
                problems.append('请确认有效包装尺寸和支持的单位。')
    missing=[LABELS[k] for k in sorted(REQUIRED-set(target))]
    if missing:
        problems.append('请补充或确认：'+'、'.join(dict.fromkeys(missing))+'。')
    for key in ['origin','destination']:
        if key in target:
            value=target[key]
            if not isinstance(value,str) or not re.fullmatch(r'[A-Z][A-Z0-9_-]{1,31}',unicodedata.normalize('NFKC',value).strip().upper()):
                problems.append('请确认'+LABELS[key]+'在历史表中的明确代码/名称；不自动把城市等同机场或港口。')
            else:
                target[key]=unicodedata.normalize('NFKC',value).strip().upper()
    if 'dangerous_goods' in target:
        # Accept explicit transport wording, never infer from an uncertain statement.
        aliases={'危化品':'危化品','危险品':'危化品',
                 '非危化品':'非危化品','非危险品':'非危化品','是':'危化品','否':'非危化品'}
        value=target['dangerous_goods']
        if not isinstance(value,str) or value.strip() not in aliases:
            problems.append('请确认危化品属性；未知不能按非危化品处理。')
        else:
            target['dangerous_goods']=aliases[value.strip()]
    if 'mode' in target:
        aliases={'海运':'海运','空运':'空运','sea':'海运','air':'空运'}
        value=target['mode']
        if not isinstance(value,str) or norm(value) not in aliases:
            problems.append('请确认运输方式为海运或空运，不跨方式放宽。')
        else:
            target['mode']=aliases[norm(value)]
    if problems:
        return {'ready':False,'questions':list(dict.fromkeys(problems))}
    # Numeric canonical fields already encode KG/CM in their names.
    target=active_query(target)
    require(REQUIRED<=set(target))
    return {'ready':True,'target':target,'questions':[]}


SOFT = {'model','gross_weight_kg','length_cm','width_cm','height_cm'}
POOL_KEYS = {'mode','carrier','currency','date_from','date_to','date_field'}
OPEN_BOUND = '1900-01-01'


def protected_scope(target):
    """Route, hazard and explicit mode/carrier/currency/date protections for history matching."""
    require(REQUIRED<=set(target))
    return query({k:v for k,v in target.items() if k not in SOFT})


def open_scope():
    """Full-history pool used to recommend after a history lookup."""
    return query({'date_from':OPEN_BOUND})


def scope(target):
    """API pool for recommendation: all transport history, keeping only explicit
    mode/carrier/currency/date limits. Route and hazard are evaluated in code so
    that plans can still be recommended when the exact route has no history."""
    require(REQUIRED<=set(target))
    pool={k:v for k,v in target.items() if k in POOL_KEYS}
    if not {'date_from','date_to'}&set(pool):
        pool['date_from']=OPEN_BOUND
    return query(pool)


def size_equal(row,target):
    return all(number(row[k])==number(target[k]) for k in ('length_cm','width_cm','height_cm'))


def evaluate(records,bills,target):
    """Use the current set at every step; absent equality preserves that set."""
    bill_map={b['bill_no']:b for b in bills}
    require(all(matches(r,bill_map[r['bill_no']],scope(target)) for r in records), 'Inquiry pool is outside API scope')
    protected=protected_scope(target)
    records=[r for r in records if matches(r,bill_map[r['bill_no']],protected)]
    equal={'material':lambda r:norm(r['model'])==norm(target['model']),
           'weight':lambda r:r.get('gross_weight_kg') is not None and
                            number(r['gross_weight_kg'])==number(target['gross_weight_kg']),
           'size':lambda r:size_equal(r,target)}
    full=[r for r in records if all(test(r) for test in equal.values())]
    if full:
        return {'match_type':'full','records':full,'pool_count':len(records),'full_count':len(full),'steps':[]}
    if not records:
        return {'match_type':'no_records','records':[],'pool_count':0,'full_count':0,'steps':[]}
    candidates=list(records);steps=[]
    for criterion,test in equal.items():
        matched=[r for r in candidates if test(r)]
        steps.append({'criterion':criterion,'before':len(candidates),'equal':len(matched),
                      'after':len(matched) if matched else len(candidates),
                      'decision':'narrow' if matched else 'keep_previous'})
        if matched:
            candidates=matched
    return {'match_type':'approximate','records':candidates,'pool_count':len(records),'full_count':0,'steps':steps}


def differences(row,target):
    result=[]
    if norm(row['model'])!=norm(target['model']):
        result.append({'field':'model','requested':target['model'],'historical':row['model']})
    for key in ('gross_weight_kg','length_cm','width_cm','height_cm'):
        historical = row.get(key)
        if historical is None:
            result.append({'field':key,'requested':target[key],'historical':None})
        elif number(historical)!=number(target[key]):
            result.append({'field':key,'requested':target[key],'historical':historical,
                           'delta':format(number(historical)-number(target[key]),'f')})
    return result


TIERS = {
    1:'同路线、同危化属性，且有同型号历史',
    2:'同路线、同危化属性',
    3:'同危化属性，起运地或目的地相同',
    4:'同危化属性（其他路线）',
    5:'同路线（危化属性不同）',
    6:'其他运输历史',
}


def tier(row,target):
    origin=norm(row['origin'])==norm(target['origin'])
    destination=norm(row['destination'])==norm(target['destination'])
    hazard=row['dangerous_goods']==target['dangerous_goods']
    if origin and destination and hazard:
        return 1 if norm(row['model'])==norm(target['model']) else 2
    if hazard and (origin or destination):return 3
    if hazard:return 4
    if origin and destination:return 5
    return 6


def recommend(records,bills,target,limit=5):
    """Rank transport plans (service provider + mode) over the full API pool.

    Order: best experience tier, tickets in that tier, total tickets, latest ETD,
    then stable provider/mode names. Amounts are whole original-currency bills."""
    bill_map={b['bill_no']:b for b in bills}
    groups={}
    for row in records:
        groups.setdefault((row['carrier'],row['mode']),[]).append(row)
    ranked=[]
    for (carrier,mode),rows in groups.items():
        best=min(tier(r,target) for r in rows)
        best_rows=[r for r in rows if tier(r,target)==best]
        best_bills=list(dict.fromkeys(r['bill_no'] for r in best_rows))
        by_currency = {}
        for bill_no in best_bills:
            bill = bill_map[bill_no]
            by_currency.setdefault(bill['currency'], []).append(bill['foreign_total'])
        amount_ranges = [
            {'currency': currency, 'min': min(totals, key=number), 'max': max(totals, key=number)}
            for currency, totals in sorted(by_currency.items())
        ]
        ranked.append({'carrier':carrier,'mode':mode,'tier':best,'tier_bills':len(best_bills),
                       'total_bills':len(set(r['bill_no'] for r in rows)),
                       'same_model_rows':sum(1 for r in rows if norm(r['model'])==norm(target['model'])),
                       'latest':max(r['etd'][:10] for r in rows),'routes':sorted({r['origin']+'→'+r['destination'] for r in best_rows})[:3],
                       'amount_ranges':amount_ranges})
    ranked.sort(key=lambda x:(x['tier'],-x['tier_bills'],-x['total_bills'],
                              tuple(-int(p) for p in x['latest'].split('-')),x['carrier'],x['mode']))
    for index,item in enumerate(ranked,1):
        item['rank']=index
    return {'total_plans':len(ranked),'items':ranked[:limit]}
