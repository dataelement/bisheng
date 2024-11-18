import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { ChevronRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import useFlowStore from "../../flowStore";
import NodeLogo from "../NodeLogo";

const isMatch = (obj, expression) => {
    const fn = new Function('value', `return ${expression}`);
    return fn(obj.value);
};

/**
 * @param  nodeId 节点id, itemKey 当前变量key, children, onSelect
 * @returns 
 */
export default function SelectVar({ nodeId, itemKey, children, onSelect }) {
    const [open, setOpen] = useState(false)
    const { flow } = useFlowStore()

    const getNodeDataByTemp = (temp) => {
        const hasChild = temp.group_params.some(group =>
            group.params.some(param => param.global)
        )

        return {
            id: temp.id,
            type: temp.type,
            name: temp.name,
            icon: <NodeLogo type={temp.type} colorStr={temp.name} />,
            desc: temp.description,
            tab: temp.tab?.value || '',
            data: hasChild ? temp.group_params : null
        }
    }
    const nodeTemps = useMemo(() => {
        if (!flow.nodes || !open) return []
        return flow.nodes.reduce((list, temp) => {
            const newNode = getNodeDataByTemp(temp.data)
            newNode.data && list.push(newNode)
            return list
        }, [])
    }, [open])

    // vars
    const [vars, setVars] = useState([])
    const currentMenuRef = useRef(null)
    const handleShowVars = (item) => {
        currentMenuRef.current = item
        // start节点 preset_question#0(中文)
        // input节点 key
        // agent xxx#0
        let _vars = []
        item.data.forEach(group => {
            group.params.forEach(param => {
                // 过滤不相同tab
                if (item.tab && param.tab && item.tab !== param.tab) return
                // 过滤当前节点的output变量
                if (nodeId === item.id && param.key.indexOf('output') === 0) return
                // 不能选自己(相同变量名视为self) param.key
                if (param.key === itemKey) return
                if (!param.global) return
                // 处理code表达式
                if (param.global.indexOf('code') === 0) {
                    let result = isMatch(param, param.global.replace('code:', ''));
                    // 没值 key补
                    if (!result.length) {
                        result = [{
                            label: param.key,
                            value: param.key
                        }]
                    }
                    _vars = [..._vars, ...result]
                } else if (param.global === 'key'
                    || (param.global === 'self' && nodeId === item.id)) {
                    _vars.push({
                        label: param.key,
                        value: param.key
                    })
                } else if (param.global === 'index') {
                    _vars.push({
                        param,
                        label: `${param.key}`,
                        value: `${param.key}`
                    })
                } else if (param.global && param.global.indexOf('=') !== -1) {
                    const [key, value] = param.global.split('=')
                    // 特殊逻辑
                    // 私有变量
                    if (key === 'self') {
                        if (nodeId === item.id && value.indexOf(itemKey) !== -1) {
                            _vars.push({
                                label: param.key,
                                value: param.key
                            })
                        }
                    } else {
                        // 从自身找是否满足表达式的条件
                        const result = isMatch(param, param.global.replace(/=(.*)/, "=== '$1'"));
                        result && _vars.push({
                            label: param.key,
                            value: param.key
                        })
                    }
                }
            });
        });

        setVars(_vars)
        setQuestions([])
    }

    // 三级变量 预置问题
    const [questions, setQuestions] = useState([])
    const handleShowQuestions = (param) => {
        const values = param.value.filter(e => e)
        setQuestions(values.map((el, index) => ({
            label: el,
            value: `${param.key}#${index}`
        })))
    }

    // clear
    useEffect(() => {
        if (!open) {
            setVars([])
            setQuestions([])
        }
    }, [open])

    return <Select open={open} onOpenChange={setOpen}>
        <SelectTrigger showIcon={false} className={'group p-0 h-auto data-[placeholder]:text-inherit border-none bg-transparent shadow-none outline-none focus:shadow-none focus:outline-none focus:ring-0'}>
            {children}
        </SelectTrigger>
        <SelectContent>
            <div className="flex ">
                <div className="w-36 border-l first:border-none overflow-y-auto max-h-[360px] scrollbar-hide">
                    {nodeTemps.map(item =>
                        <div
                            className="relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                            onMouseEnter={() => handleShowVars(item)}
                        >
                            {item.icon}
                            <span className="w-28 overflow-hidden text-ellipsis ml-2">{item.name}</span>
                            <ChevronRight className="size-4" />
                        </div>
                    )}
                </div>
                {!!vars.length && <div className="w-36 border-l first:border-none">
                    {vars.map(v =>
                        <div
                            className="relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                            onClick={() => {
                                if (v.param) return
                                onSelect(currentMenuRef.current, v)
                                setOpen(false)
                            }}
                            onMouseEnter={() => v.param && handleShowQuestions(v.param)}>
                            <span className="w-28 overflow-hidden text-ellipsis">{v.label}</span>
                            {v.param && <ChevronRight className="size-4" />}
                        </div>
                    )}
                </div>}
                {
                    !!questions.length && <div className="w-36 border-l first:border-none">
                        {questions.map(q =>
                            <div
                                className="relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                                onClick={() => {
                                    onSelect(currentMenuRef.current, q)
                                    setOpen(false)
                                }}>
                                <span className="w-28 overflow-hidden text-ellipsis">{q.label}</span>
                            </div>
                        )}
                    </div>
                }
            </div>
        </SelectContent>
    </Select>
};
