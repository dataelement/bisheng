#!/usr/bin/env python3
"""Deterministic supplier recommendation: history suppliers plus QPL/QSL catalog suppliers.

Ranking is fixed code, never a model judgement:
  tier 1 (history)  suppliers that actually sold this model and pass the buyer list;
  tier 2 (spec)     QSL suppliers whose standard code equals a code in the model;
  tier 3 (category) catalog suppliers approved for the inferred material category;
  tier 4 (channel)  catalog material distributors, used only when no category is known.
History and catalog leads are separate groups, with no shared rank or preferred supplier. A recommendation is an inquiry suggestion,
not a quote, approval verdict or order.
"""

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

import qualification_lookup

MAX_ROWS = 10

TIER_LABEL = {1: "本型号历史供货", 2: "QSL规范号一致", 3: "名录范围线索", 4: "通用经营范围"}

SCOPE_LABELS = {"AFM-002-1":"材料分销", "AFM-002-2":"材料零件制造", "AFM-001-2":"航空结构按图制造", "AFM-001-1":"航空结构设计与制造", "AFM-002-3":"材料细节零件制造", "GP-1-73D":"生产及其他消耗品"}

# Catalog scope per inferred category. QSL only covers metals (COMAC part 2 list).
CATEGORIES = {
    "aluminium": {"label": "铝合金材料", "qsl": "铝材-铝合金", "qpl": ["AFM-002-1", "AFM-002-2"]},
    "titanium": {"label": "钛合金材料", "qsl": "钛材-钛合金", "qpl": ["AFM-002-1", "AFM-002-2"]},
    "steel": {"label": "钢材", "qsl": "钢材-钢", "qpl": ["AFM-002-1", "AFM-002-2"]},
    "superalloy": {"label": "高温合金", "qsl": "钢材-高温合金", "qpl": ["AFM-002-1", "AFM-002-2"]},
    "copper": {"label": "铜合金材料", "qsl": "铜材-铜合金", "qpl": ["AFM-002-1", "AFM-002-2"]},
    "chemical": {"label": "液体/涂层/密封胶等化工耗材", "qsl": None, "qpl": ["GP-1-73D", "AFM-002-1"]},
    "nonmetal": {"label": "非金属/复合材料", "qsl": None, "qpl": ["AFM-002-1", "AFM-002-2"]},
    "structure": {"label": "结构件/成品零件", "qsl": None, "qpl": ["AFM-001-2", "AFM-001-1", "AFM-002-3"]},
}
CHANNEL_GROUPS = ["AFM-002-1", "AFM-001-4", "SAT-1-1"]

# Order matters: the first hit wins. Keywords are matched on NFKC/casefolded text.
KEYWORDS = [
    ("superalloy", ["高温合金", "inconel", "waspaloy"]),
    ("titanium", ["钛", "titanium", "ti-6al"]),
    ("aluminium", ["铝", "aluminum", "aluminium"]),
    ("copper", ["铜", "copper", "bronze", "brass"]),
    ("steel", ["钢", "steel", "不锈"]),
    (
        "chemical",
        [
            "液体",
            "涂料",
            "涂层",
            "底漆",
            "油漆",
            "密封",
            "胶",
            "油",
            "溶剂",
            "清洗",
            "润滑",
            "化学",
            "primer",
            "sealant",
            "adhesive",
            "paint",
            "coating",
            "fluid",
            "grease",
        ],
    ),
    ("nonmetal", ["复合材料", "非金属", "预浸", "纤维", "composite", "prepreg"]),
    ("structure", ["壁板", "翼尖", "成品", "零件", "组件", "结构件", "panel", "assembly"]),
]
# Boeing material specification series (series-level inference, flagged for business review).
BMS_SERIES = {"3": "chemical", "5": "chemical", "10": "chemical", "8": "nonmetal", "7": "steel"}
AMS_CODE = re.compile(r"AMS[- ]?(?:QQ-A-\d+/\d+|\d{4}[A-Z]?)", re.I)
BMS_CODE = re.compile(r"BMS\s*(\d+)\s*-\s*\d+", re.I)


def norm(value):
    return qualification_lookup.norm(value)


def _code(value):
    return re.sub(r"[\s-]", "", norm(value)).upper()


def profile(model, materials=()):
    """Infer spec codes and one material category from the model and history material text."""
    text = " ".join([str(model or "")] + [str(m) for m in materials if m])
    codes = sorted({_code(m.group(0)) for m in AMS_CODE.finditer(text)})
    category, basis = None, None
    bms = BMS_CODE.search(str(model or ""))
    lowered = norm(text)
    for key, words in KEYWORDS:
        hit = next((w for w in words if w in lowered), None)
        if hit:
            category, basis = key, "物料描述含“" + hit + "”"
            break
    if category is None and bms and bms.group(1) in BMS_SERIES:
        category = BMS_SERIES[bms.group(1)]
        basis = "波音材料规范BMS" + bms.group(1) + "系列推断（系列级，待业务确认）"
    if category is None and codes:
        basis = "型号含规范号" + "、".join(codes)
    return {"codes": codes, "category": category, "basis": basis, "materials": sorted({str(m) for m in materials if m})}


def _qsl_candidates(index, prof):
    spec, category = defaultdict(list), defaultdict(list)
    wanted = CATEGORIES.get(prof["category"] or "", {}).get("qsl")
    for row in index["qsl"]["records"]:
        if row.get("row_kind") != "supplier_record" or not norm(row.get("supplier_name")):
            continue
        name = str(row["supplier_name"]).strip()
        row_codes = {_code(c) for c in re.split(r"[\n;；,，]", str(row.get("standard_code") or "")) if c.strip()}
        if prof["codes"] and row_codes & set(prof["codes"]):
            spec[name].append(row)
        elif wanted and row.get("material_category") == wanted:
            category[name].append(row)
    result = []
    for tier, groups in ((2, spec), (3, category)):
        for name, rows in groups.items():
            forms = sorted({str(r.get("product_form") or "").replace("\n", "") for r in rows if r.get("product_form")})
            aircraft = sorted({str(r.get("aircraft")) for r in rows if r.get("aircraft")})
            standards = sorted(
                {str(r.get("standard_code") or "").replace("\n", "/") for r in rows if r.get("standard_code")}
            )
            reason = (
                "QSL规范" + "、".join(standards[:3])
                if tier == 2
                else "QSL" + CATEGORIES[prof["category"]]["qsl"] + "登记" + str(len(rows)) + "项"
            )
            if forms:
                reason += "；形态" + "、".join(forms[:3])
            if aircraft:
                reason += "；适用" + "、".join(aircraft)
            result.append(
                {
                    "tier": tier,
                    "name": name,
                    "list": "qsl",
                    "score": len(rows),
                    "code": rows[0].get("supplier_code"),
                    "country": rows[0].get("supplier_country"),
                    "reason": reason,
                    "evidence_rows": [r.get("source_row") for r in rows[:5]],
                    "matched_standards": standards, "product_forms": forms, "aircraft": aircraft,
                    "material_category": "、".join(sorted({str(r.get("material_category") or "") for r in rows if r.get("material_category")})),
                    "match_kind": "standard_equal" if tier == 2 else "material_category",
                }
            )
    return result


def _qpl_candidates(index, groups, tier):
    by_company = defaultdict(lambda: {"mapped": set(), "all": set(), "country": None, "code": None, "rows": [], "scopes": {}})
    for row in index["qpl"]["records"]:
        if row.get("row_kind") != "supplier_record" or not norm(row.get("company_name")):
            continue
        item = by_company[norm(row["company_name"])]
        item["name"] = str(row["company_name"]).strip()
        item["all"].add(row["product_group_code"])
        if row["product_group_code"] in groups:
            item["mapped"].add(row["product_group_code"])
            code=row["product_group_code"]
            item["scopes"][code]=SCOPE_LABELS.get(code) or str(row.get("product_group") or code)
            item["country"] = item["country"] or row.get("country")
            item["code"] = item["code"] or row.get("company_code")
            if len(item["rows"]) < 5:
                item["rows"].append(row.get("source_page"))
    result = []
    for item in by_company.values():
        if not item["mapped"]:
            continue
        result.append(
            {
                "tier": tier,
                "name": item["name"],
                "list": "qpl",
                # More mapped groups first, then the category's primary group, then approval breadth.
                "score": len(item["mapped"]) * 1000 + (100 if groups[0] in item["mapped"] else 0) + len(item["all"]),
                "code": item["code"],
                "country": item["country"],
                "reason": "QPL产品组"
                + "、".join(sorted(item["mapped"]))
                + "；共获批"
                + str(len(item["all"]))
                + "个产品组",
                "evidence_rows": item["rows"],
                "matched_scopes": [{"code":code,"label":item["scopes"][code]} for code in sorted(item["mapped"])],
                "match_kind":"business_scope" if tier == 3 else "general_channel",
            }
        )
    return result


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _history_candidates(suppliers):
    merged = {}
    for s in suppliers or []:
        item = merged.setdefault(
            s.get("supplier_id"),
            {
                "tier": 1,
                "name": "、".join(s.get("supplier_names") or []) or str(s.get("supplier_id")),
                "supplier_id": s.get("supplier_id"),
                "records": 0,
                "latest": "",
                "prices": {},
                "list": None,
                "qualification": s.get("qualification"),
            },
        )
        item["records"] += s.get("record_count") or 0
        item["latest"] = max(item["latest"], s.get("latest_confirmed_date") or "")
        c = s.get("conditions") or {}
        price = _decimal(s.get("historical_min_unit_price"))
        if price is not None:
            key = (c.get("currency") or "", c.get("unit") or "")
            item["prices"][key] = min(price, item["prices"].get(key, price))
    items = list(merged.values())
    currencies = {k for i in items for k in i["prices"]}
    comparable = len(currencies) == 1
    for i in items:
        price = i["prices"].get(next(iter(currencies))) if comparable else None
        i["price_key"] = price if price is not None else Decimal("Infinity")
        parts = ["本型号历史采购" + str(i["records"]) + "条"]
        if i["latest"]:
            parts.append("最近" + i["latest"])
        if i["prices"]:
            parts.append(
                "历史最低单价"
                + "；".join(str(v) + " " + k[0] + ("/" + k[1] if k[1] else "") for k, v in sorted(i["prices"].items()))
            )
        q = i.get("qualification") or {}
        if q.get("whitelist_status") == "listed":
            parts.append("已列入本次甲方名录")
        i["reason"] = "；".join(parts)
    # More history first, then the most recent, then the lower price when one currency/unit applies.
    items.sort(key=lambda i: (-i["records"], _neg_date(i["latest"]), i["price_key"], i["name"]))
    return items, comparable


def _neg_date(value):
    return tuple(-int(x) for x in re.findall(r"\d+", value or "")) or (0,)


def _category_from_spec(index, prof):
    """A spec code listed in QSL fixes the material category, also for non-COMAC buyers."""
    found = defaultdict(int)
    for row in index["qsl"]["records"]:
        row_codes = {_code(c) for c in re.split(r"[\n;；,，]", str(row.get("standard_code") or "")) if c.strip()}
        if row_codes & set(prof["codes"]):
            found[row.get("material_category")] += 1
    for key, value in CATEGORIES.items():
        if found and value["qsl"] == max(found, key=found.get):
            prof["category"] = key
            prof["basis"] = "规范号" + "、".join(prof["codes"]) + "在QSL中登记为" + value["qsl"]
            return


def recommend(model, purchaser, materials=(), history_suppliers=(), index=None):
    prof = profile(model, materials)
    if index is not None and prof["codes"] and not prof["category"]:
        _category_from_spec(index, prof)
    route = qualification_lookup.route(purchaser)
    use_qsl = route in (None, "skip", "qsl")
    use_qpl = route in (None, "skip", "qpl")
    notes = []
    history, comparable = _history_candidates(history_suppliers)
    if history and len(history) > 1 and not comparable:
        notes.append("历史价格币种或单位不一致，历史供货商之间不按价格排序。")
    catalog = []
    if index is not None:
        if use_qsl:
            catalog += _qsl_candidates(index, prof)
            if route == "qsl" and not prof["category"] and not prof["codes"]:
                notes.append("未能从型号或物料描述识别物料类别，商飞QSL（只收录金属材料）无法按类别匹配；补充物料类别或规范号后可再推荐。")
            elif route == "qsl" and not CATEGORIES.get(prof["category"] or "",{}).get("qsl") and not prof["codes"]:
                notes.append("商飞QSL当前只收录金属材料，本物料类别不在其覆盖范围内。")
        if use_qpl and prof["category"]:
            catalog += _qpl_candidates(index, CATEGORIES[prof["category"]]["qpl"], 3)
        if use_qpl and not prof["category"] and not any(c["tier"] == 2 for c in catalog):
            catalog += _qpl_candidates(index, CHANNEL_GROUPS, 4)
            notes.append(
                "未能从型号或物料描述识别物料类别，以下名录候选按通用材料分销渠道给出；补充物料类别后推荐会更准确。"
            )
    else:
        notes.append("名录资源不可用，仅按历史供货排序。")
    seen = {norm(h["name"]) for h in history}
    for h in history:
        hit = next((c for c in catalog if norm(c["name"]) == norm(h["name"])), None)
        if hit:
            h["reason"] += "；名录：" + hit["reason"]
    catalog = [c for c in catalog if norm(c["name"]) not in seen]
    catalog.sort(key=lambda c: (c["tier"], -c["score"], norm(c["name"])))
    # One company is one catalog lead: retain the strongest *evidence type*, not a quality ranking.
    unique = {}
    for item in catalog:
        unique.setdefault(norm(item['name']),item)
    catalog=list(unique.values())
    history_total,catalog_total=len(history),len(catalog)
    history=history[:MAX_ROWS];catalog=catalog[:MAX_ROWS]
    category_label=CATEGORIES.get(prof['category'] or '',{}).get('label') or '未识别类别'
    for i,item in enumerate(history,1):
        item.update(group='history',rank=i)
    for i,item in enumerate(catalog,1):
        item.update(group='catalog',rank=None,candidate_ref='C'+str(i).zfill(2))
        if item['list']=='qpl':
            item['match_label']='QPL经营范围' if item['tier']==3 else 'QPL通用渠道'
            scope='、'.join(x['label']+'（'+x['code']+'）' for x in item.get('matched_scopes',[]))
            item['reason']='名录登记范围：'+scope+'；这是经营/制造范围的宽筛线索，未验证可供当前具体物料或型号'
        else:
            item['match_label']='QSL规范号一致' if item['tier']==2 else 'QSL物料大类'
            if item['tier']==2:
                same=sorted(set(prof['codes']) & {_code(c) for c in item.get('matched_standards',[])})
                item['reason']='本次规范与名录一致：'+'、'.join(same)
            else:
                item['reason']='本次识别：'+category_label+'；名录登记大类：'+str(item.get('material_category') or '未提供')+'；仅物料大类一致，不是具体型号一致'
            if item.get('product_forms'):item['reason']+='；名录形态：'+'、'.join(item['product_forms'][:3])
            if item.get('aircraft'):item['reason']+='；名录机型：'+'、'.join(item['aircraft'])
            item['reason']+='；具体型号、尺寸及适用范围仍待确认'
    used = [k for k, on in (("qpl", use_qpl), ("qsl", use_qsl)) if on]
    return {"model":model,"purchaser":purchaser,"route":route,"profile":prof,
            "items":history+catalog,"history_items":history,"catalog_items":catalog,
            "history_total":history_total,"catalog_total":catalog_total,"total":history_total+catalog_total,
            "notes":notes,"source":{k:index[k]["source"] for k in used} if index is not None else {}}


def render(rec, cell, table):
    prof=rec['profile'];history=rec['history_items'];catalog=rec['catalog_items']
    route_text={'qpl':'空客，历史供应商须符合所给QPL名录条件','qsl':'商飞，历史供应商须符合所给QSL名录条件','skip':'其他甲方，名录仅作补充线索',None:'未指定甲方，名录仅作补充线索'}[rec['route']]
    category=CATEGORIES.get(prof['category'] or '',{}).get('label') or '未识别类别'
    parts=['**供应商推荐 · '+cell(rec['model'])+'**','本次甲方：'+cell(rec['purchaser'] or '未指定')+'（'+route_text+'）。',
           '物料识别：'+category+('；识别依据：'+prof['basis'] if prof.get('basis') else '')+'。',
           '**一、本型号历史供应商**',
           '以下来自当前型号、当前筛选条件下的历史采购；与名录候选分开展示，不合并排名。']
    if history:
        parts.append(table(['组内序号','历史供应商','本型号历史明细数','理由'],[[str(i),x['name'],str(x['records']),x['reason']] for i,x in enumerate(history,1)]))
        parts.append('本组共'+str(rec['history_total'])+'家，展示'+str(len(history))+'家。组内沿用历史供货记录排序：采购次数、最近采购时间，同币种和单位时再比较历史最低价；不代表综合履约排名。')
    else:parts.append('当前查询条件下没有可展示的本型号历史供应商；名录候选不补作历史供货记录。')
    parts+=['**二、名录候选供应商（型号供货待确认）**',
            '这些主体没有本次结果中的本型号历史供货证据，仅由所给名录提供寻源线索；不列首选、不与历史供应商一起排名。候选编号用于指认，不表示优劣。']
    if catalog:
        if any(i['list']=='qpl' for i in catalog):
            parts.append('QPL线索说明：本次物料识别为“'+category+'”，但这里实际按名录的经营或制造范围检索，未细分到该具体物料；范围登记不能证明可以供应本型号。每家的具体登记范围见下表。')
        if any(i['list']=='qsl' for i in catalog):
            parts.append('QSL线索说明：“规范号一致”指输入或历史物料描述中的规范号与名录登记相同；“物料大类”只指识别类别与名录大类一致。名录形态、机型、尺寸与具体型号的适用性仍需逐项核实。')
        parts.append(table(['候选编号','供应商','线索类型','理由'],[[i['candidate_ref'],i['name'],i['match_label'],i['reason']] for i in catalog]))
        parts.append('名录候选共'+str(rec['catalog_total'])+'家，展示'+str(len(catalog))+'家；展示顺序仅按证据类型、登记命中及名称整理，不是供货能力或质量价格排名。')
    else:parts.append('当前物料信息和所给名录范围内，没有可展示的名录候选。')
    parts.extend(rec['notes'])
    if rec.get('source'):parts.append('名录来源：'+'；'.join(cell(v.get('file')) for v in rec['source'].values() if v)+'。')
    choice = '，或提供当前名录候选编号（如' + cell(catalog[0]['candidate_ref']) + '）' if catalog else ''
    parts.append('如需确定询价对象，请指定供应商名称' + choice + '。未指定对象时不代选；仅记录本对话询价对象，不报价、审批或下单。')
    return '\n\n'.join(parts)
