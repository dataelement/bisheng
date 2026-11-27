"""Pure business recap copied from the verified current adapter; no platform dependency."""
def business_process(scene, request, result):
    import json
    if not isinstance(request,dict) or not isinstance(result,dict):
        return result.get('answer','') if isinstance(result,dict) else ''
    answer=result.get('answer','')
    if not isinstance(answer,str) or not answer:return answer
    if answer.startswith('```business-process\n'):return answer
    action=request.get('action','show'); outcome=result.get('outcome','unknown')
    names={'procurement':'采购','transport':'运输','customs':'报关'}
    nodes=[]
    def add(title,summary,status='done',details=None):
        nodes.append({'title':title,'summary':str(summary)[:500],'status':status,
                      'details':[str(x)[:600] for x in (details or [])][:8]})
    labels={'model':'规格型号','target_model':'当前型号','purchaser':'本次甲方','origin':'起点','destination':'目的地',
            'mode':'运输方式','dangerous_goods':'危化属性','net_weight_kg':'净重kg','gross_weight_kg':'毛重kg',
            'house_numbers':'分单号','bill_numbers':'账单号','date_from':'起始日期','date_to':'截止日期',
            'currency':'币种','carrier':'服务商','sort':'排序','reference':'费用引用','supplier_name':'询价对象'}
    conditions=[]
    for source in [request,request.get('query'),request.get('target'),request.get('set')]:
        if not isinstance(source,dict):continue
        for key,value in source.items():
            if key in labels and value is not None:
                conditions.append(labels[key]+'：'+str(value)[:160])
    action_names={'history':'历史查询','suppliers':'供应商选取','compare':'记录比价','filter':'条件筛选',
                  'reset':'恢复条件','show':'查看结果','inquiry':'寻找历史参考','detail':'单据追溯',
                  'confirm':'确认询价对象','unconfirm':'撤销确认','confirmations':'查看确认记录',
                  'choose':'选择近似型号','resolve':'型号核对','help':'输入引导','explain_limits':'说明数据边界'}
    add('理解本轮需求',action_names.get(action,'按本轮要求处理'),details=conditions)
    failed=outcome in {'execution_error','source_unavailable','state_error','validation_error','invalid_request','stale_source','stale_reference','query_error','invalid_query','file_or_state_error','api_failure','api_error','api_timeout','invalid_filter','invalid_regex'}
    waiting=(result.get('status')=='user_clarification' or outcome in {'needs_clarification','needs_input','needs_query','needs_new_query','needs_correction','pending_correction','pending_candidates','awaiting_correction','awaiting_selection','no_exact_match','invalid_selection','page_out_of_range'})
    if scene=='procurement' and '请核对是否需要修正' in answer:waiting=True
    empty=outcome in {'no_records','no_exact_history','no_history'}
    if failed:
        add('本轮处理未完成','本次失败不能解释为没有历史记录','error',[answer[:450]])
        add('恢复处理','请按错误提示重试或补充；未获得的数据不作结论','pending')
    elif scene=='procurement':
        models=result.get('models') or []
        if isinstance(models,list) and models:
            if '型号差异：原始目标为' in answer:
                add('按确认执行近似召回','返回'+str(len(models[:3]))+'个近似型号，按型号分别展示',details=['型号：'+str(m.get('model','')) for m in models[:3] if isinstance(m,dict)]+['规格差异和可替代性尚未核验，不合并不同型号价格'])
            for model in models[:3]:
                if not isinstance(model,dict):continue
                c=model.get('counts') or {}; sc=model.get('supplier_counts') or {}
                add('核对历史与筛选',str(model.get('model','当前型号'))+' · 原批次'+str(c.get('original_batch_records',0))+'条，当前匹配'+str(c.get('total_matches',0))+'条',
                    'empty' if not c.get('total_matches') else 'done',
                    ['生效筛选：'+json.dumps(model.get('active_filters',{}),ensure_ascii=False),'本次数据已由固定执行入口校验；价格按型号分别展示'])
                recommendation_in_answer = model.get('view')=='history' and '**供应商推荐' in answer
                if model.get('view')=='suppliers' or sc.get('historical_supplier_groups',0) or recommendation_in_answer:
                    buyer=model.get('purchaser') or request.get('purchaser')
                    if buyer in ['空客','空中客车','Airbus','airbus','商飞','中国商飞','COMAC','comac']:
                        name='QPL' if buyer in ['空客','空中客车','Airbus','airbus'] else 'QSL'
                        recap = ('已依据'+name+'名单生成本轮推荐；具体候选与证据见下方' if recommendation_in_answer else
                                 '历史条件组'+str(sc.get('historical_supplier_groups',0))+'项 · 保留'+str(sc.get('total_items',0))+'项 · 排除或待核验'+str(sc.get('excluded_supplier_groups',0))+'项')
                        add('按甲方核验 '+name,recap,
                            'done', ['名单命中、未列入、待核验分别按实际结果显示','所给版本的主体和产品适用范围见业务结果中的名录证据'])
                    else:add('核对名录要求','本次甲方未指定，或按现有范围无需核验名录','skipped')
            add('形成本轮结果','按生效条件展示；价格排序与可比口径详见下方',details=['沿用用户当前排序和筛选，不生成新的报价或交付指标'])
        elif action in ['confirm','unconfirm','confirmations']:
            add('更新本对话确认记录',{'confirm':'记录本次询价对象','unconfirm':'撤销本次确认','confirmations':'读取已有确认记录'}[action],details=['记录仅限本对话，不向订单系统下单'])
        elif waiting or empty:
            add('核对型号与可用数据','需要补充或选择后继续；具体原因见下方','waiting' if waiting else 'empty',[answer[:450]])
        else:
            add('执行本轮处理','固定入口已返回本轮结果',details=['动作：'+str(action),'结果状态：'+str(outcome)])
        if waiting:add('等待你确认或补充','后续步骤暂停，按下方提示回复即可','waiting')
        elif empty:add('本轮查询无匹配','仅针对当前取数范围和条件，不表示全部历史无记录','empty')
        elif action not in ['confirm','unconfirm','confirmations']:add('查看与继续','可继续筛选、比较或确认询价对象')
    else:
        if waiting:
            add('核对必要条件','需要补齐条件后继续匹配','waiting',[answer[:450]])
            add('等待你补充','尚未完成匹配和费用判断','pending')
        elif outcome=='capability_limits':add('核对数据边界','当前能力与缺失项见下方说明')
        else:
            match=result.get('match') or {};counts=result.get('counts') or {}
            kind=match.get('match_type','history')
            history_empty = empty or kind=='no_records'
            recommendations=result.get('recommendation') or []
            if isinstance(recommendations,list) and recommendations:
                tiers=[r.get('tier',0) for r in recommendations if isinstance(r,dict)]
                cross=bool(tiers) and min(tiers)>=3
                add('整理'+('运输方案' if scene=='transport' else '报关代理')+'候选',str(len(recommendations))+'项'+('相近经验推荐；当前硬条件没有历史匹配' if history_empty else '历史经验推荐'),
                    details=['跨线路或目的港经验只用于候选参考，不作为当前硬条件命中的费用'] if cross else ['推荐依据和历史金额口径见下方；不构成本次正式报价'])
            labels_match={'history':'按单据与条件查询历史','full':'完整条件匹配','approximate':'近似条件匹配','no_records':'当前条件暂无匹配'}
            add('核对查询与匹配',labels_match.get(kind,'按当前条件匹配'),'empty' if history_empty else 'done',
                ['保护条件：'+('线路、运输方式、危化属性' if scene=='transport' else '目的港、危化属性；重量采用毛重口径'),
                 '逐级匹配步骤：'+json.dumps(match.get('steps',[]),ensure_ascii=False)[:550]])
            if result.get('reference_strength')=='protected_only':
                add('核对参考强度','仅保护条件命中，物料、重量和尺寸均未匹配；属于弱参考',details=['历史总额不构成本次正式报价，不能将弱匹配讲成同条件价格'])
            if counts:
                add('核对费用与完整覆盖',str(counts.get('matched_details',0))+'条命中明细 · '+str(counts.get('unique_bills',0))+'张去重账单',
                    'empty' if history_empty else 'done',['共享账单按完整覆盖展示，总额去重，不自动分摊','金额、币种、日期及匹配差异见业务结果'])
            add('展示'+('单据详情' if action=='detail' else '历史参考'), '当前硬条件无历史匹配；候选推荐另行说明' if history_empty else '结果与依据已返回，可继续查看详情或调整条件','empty' if history_empty else 'done')
    demo=any(str(v).startswith('DEMO-Q') for v in [request.get('model'),request.get('target_model'),*[m.get('model') for m in result.get('models',[]) if isinstance(m,dict)]])
    payload={'version':1,'scene':scene,'title':names.get(scene,'业务')+'分析过程','action':action,
             'outcome':outcome,'mode':'execution_recap','demo':demo,'conditions':conditions[:12],'nodes':nodes[:12]}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('`','\\u0060')
    return '```business-process\n'+encoded+'\n```\n\n'+('> 模拟演示数据：型号、订单、价格与日期为合成；名单证据引用所提供版本。\n\n' if demo else '')+answer
