"""Deterministic inquiry matching, following the reviewed customs flowchart.

The exact history API supplies a route pool. Never use associated-only bill rows
as candidates, never restart a narrowing step from the original pool.
"""
from decimal import Decimal
import re
import unicodedata

from contract import customs_fee, ContractError, encode, matches, norm, number, query, require

STRATEGY = 'customs-flow361-gross-v2-recommend'
REQUIRED = {'destination','model','gross_weight_kg','length_cm','width_cm','height_cm','dangerous_goods'}
OPTIONAL = {'package_count','carrier','currency','date_from','date_to','date_field'}
CANONICAL = REQUIRED | OPTIONAL
RAW_FIELDS = {'gross_weight','packaging'}
WEIGHT_UNITS = {'kg':'1','kgs':'1','千克':'1','公斤':'1','g':'0.001','克':'0.001',
                't':'1000','吨':'1000','lb':'0.45359237','lbs':'0.45359237','磅':'0.45359237'}
DIMENSION_UNITS = {'cm':'1','厘米':'1','mm':'0.1','毫米':'0.1','m':'100','米':'100',
                   'in':'2.54','inch':'2.54','inches':'2.54','英寸':'2.54'}
LABELS = {'destination':'目的港','model':'规格型号','gross_weight_kg':'毛重及单位',
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
            problems.append('请明确有效毛重及支持的重量单位，不以净重或计费重替代。')
    if 'packaging' in raw:
        require(not {'length_cm','width_cm','height_cm'} & set(target), 'Conflicting packaging dimensions')
        value=raw['packaging']
        require(isinstance(value,dict) and not set(value)-{'length','width','height','unit','count'}, 'Unknown packaging field')
        if not {'length','width','height','unit'} <= set(value):
            problems.append('请补充包装长、宽、高和尺寸单位。')
        else:
            try:
                for axis in ['length','width','height']:
                    target[axis+'_cm']=convert(value[axis],value['unit'],DIMENSION_UNITS)
                if 'count' in value:
                    require(type(value['count']) is int and 1<=value['count']<=1000000)
                    require('package_count' not in target or
                            (type(target['package_count']) is int and target['package_count']==value['count']),
                            'Conflicting package counts')
                    target['package_count']=value['count']
            except ContractError:
                problems.append('请确认有效包装尺寸、支持的单位及正整数包装数量。')
    missing=[LABELS[k] for k in sorted(REQUIRED-set(target))]
    if missing:
        problems.append('请补充或确认：'+'、'.join(dict.fromkeys(missing))+'。')
    if 'destination' in target:
        value=target['destination']
        if not isinstance(value,str) or not value.strip() or value.strip()=='上海':
            problems.append('请明确目的港为上海港或上海浦东机场等到达港。')
    if 'dangerous_goods' in target:
        # Accept explicit customs wording, never infer from an uncertain statement.
        aliases={'危化品':'危化品','危险品':'危化品',
                 '非危化品':'非危化品','非危险品':'非危化品','是':'危化品','否':'非危化品','普货':'非危化品'}
        value=target['dangerous_goods']
        if not isinstance(value,str) or value.strip() not in aliases:
            problems.append('请确认危化品属性；未知不能按非危化品处理。')
        else:
            target['dangerous_goods']=aliases[value.strip()]
    if problems:
        return {'ready':False,'questions':list(dict.fromkeys(problems))}
    # Numeric canonical fields already encode KG/CM in their names.
    target=query(target)
    require(REQUIRED<=set(target))
    return {'ready':True,'target':target,'questions':[]}


SOFT = {'model','gross_weight_kg','length_cm','width_cm','height_cm','package_count'}
POOL_KEYS = {'carrier','currency','date_from','date_to','date_field'}
OPEN_BOUND = '1900-01-01'


def protected_scope(target):
    """Destination, hazard and explicit agent/currency/date protections for history matching."""
    require(REQUIRED<=set(target))
    return query({k:v for k,v in target.items() if k not in SOFT})


def scope(target):
    """API pool for recommendation: every agent's history, keeping only explicit
    agent/currency/date limits. Destination and hazard are evaluated in code so
    that agents can still be recommended when the exact port/hazard has no history."""
    require(REQUIRED<=set(target))
    pool={k:v for k,v in target.items() if k in POOL_KEYS}
    if not {'date_from','date_to'}&set(pool):
        pool['date_from']=OPEN_BOUND
    return query(pool)


def size_equal(row,target):
    keys=['length_cm','width_cm','height_cm']+(['package_count'] if 'package_count' in target else [])
    return all(number(row[k])==number(target[k]) for k in keys)


def evaluate(records,bills,target):
    """Use the current set at every step; absent equality preserves that set."""
    bill_map={b['bill_no']:b for b in bills}
    require(all(matches(r,bill_map[r['bill_no']],scope(target)) for r in records), 'Inquiry pool is outside API scope')
    protected=protected_scope(target)
    records=[r for r in records if matches(r,bill_map[r['bill_no']],protected)]
    equal={'material':lambda r:norm(r['model'])==norm(target['model']),
           'weight':lambda r:number(r['gross_weight_kg'])==number(target['gross_weight_kg']),
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
    for key in ['gross_weight_kg','length_cm','width_cm','height_cm']+(['package_count'] if 'package_count' in target else []):
        if number(row[key])!=number(target[key]):
            result.append({'field':key,'requested':target[key],'historical':row[key],
                           'delta':format(number(row[key])-number(target[key]),'f')})
    return result


TIERS = {
    1:'同目的港、同危化属性，且有同型号历史',
    2:'同目的港、同危化属性',
    3:'同危化属性（其他目的港）',
    4:'同目的港（危化属性不同）',
    5:'其他报关历史',
}


def tier(row,target):
    port=norm(row['destination'])==norm(target['destination'])
    hazard=row['dangerous_goods']==target['dangerous_goods']
    if port and hazard:
        return 1 if norm(row['model'])==norm(target['model']) else 2
    if hazard:return 3
    if port:return 4
    return 5


def recommend(records,bills,target,limit=5):
    """Rank agents deterministically over the full API pool.

    Order: best experience tier, then the number of tickets in that tier, then
    total tickets, then the latest history date, then the lower median bill total
    (only compared within the same currency). Fees are history references only."""
    bill_map={b['bill_no']:b for b in bills}
    groups={}
    for row in records:
        groups.setdefault(row['carrier'],[]).append(row)
    ranked=[]
    for carrier,rows in groups.items():
        best=min(tier(r,target) for r in rows)
        best_rows=[r for r in rows if tier(r,target)==best]
        best_bills=list(dict.fromkeys(r['bill_no'] for r in best_rows))
        all_bills=list(dict.fromkeys(r['bill_no'] for r in rows))
        currencies=list(dict.fromkeys(bill_map[b]['currency'] for b in best_bills))
        amounts=sorted((customs_fee(bill_map[b]) for b in best_bills if bill_map[b]['currency']==currencies[0] and customs_fee(bill_map[b]) is not None),key=number)
        median=number(amounts[len(amounts)//2]) if amounts else Decimal('Infinity')
        same_model=sum(1 for r in rows if norm(r['model'])==norm(target['model']))
        same_port_hazard=len({r['bill_no'] for r in rows if tier(r,target)<=2})
        latest=max(r['history_date'][:10] for r in rows)
        ranked.append({'carrier':carrier,'tier':best,'tier_bills':len(best_bills),'total_bills':len(all_bills),
                       'same_port_hazard_bills':same_port_hazard,'same_model_rows':same_model,'latest':latest,
                       'currency':currencies[0],'fee_min':amounts[0] if amounts else None,'fee_max':amounts[-1] if amounts else None,'fee_median':median,
                       'sample_bills':best_bills[:3]})
    ranked.sort(key=lambda x:(x['tier'],-x['tier_bills'],-x['total_bills'],
                              tuple(-int(p) for p in x['latest'].split('-')),x['currency'],x['fee_median'],x['carrier']))
    for index,item in enumerate(ranked,1):
        item['rank']=index
    return {'total_agents':len(ranked),'items':ranked[:limit]}
