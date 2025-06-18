import { Checkbox } from "@/components/bs-ui/checkBox";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { cname } from "@/components/bs-ui/utils";
import { cloneDeep } from "lodash-es";
import { ChevronRight } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import useFlowStore from "../../flowStore";
import NodeLogo from "../NodeLogo";

// 全选 半选 未选
const enum SelectStatus {
    Uncheck = false,
    HalfCheck = 'indeterminate',
    Check = true,
}

const isMatch = (obj, expression) => {
    // 临时关闭 file类型表单变量
    if (obj.key === 'form_input') {
        expression = "value.filter(el => el.type !== 'file').map(el => ({ label: el.key, value: el.key }))"
    }
    const fn = new Function('value', `return ${expression}`);
    return fn(obj.value);
};

// 特殊结构提取变量
const getSpecialVar = (obj, type, onlyImg = false) => {
    switch (type) {
        case 'item:form_input':
            return obj.value.reduce((res, item) => {
                if (item.type === 'file') {
                    // if (item.multiple) return res
                    // res.push({ label: item.key, value: item.key })
                    if (!onlyImg) {
                        res.push({ label: item.file_content, value: item.file_content })
                        res.push({ label: item.file_path, value: item.file_path })
                    }
                    item.file_types.includes('image') && res.push({ label: item.image_file, value: item.image_file })
                    item.file_types.includes('audio') && res.push({ label: item.audio_file, value: item.audio_file })
                } else if (!onlyImg) {
                    res.push({ label: item.key, value: item.key })
                }
                return res
            }, [])
        case 'item:input_list': 
            if (!obj.value.length) return []
            if (!obj.value[0].value) return []
            const param = cloneDeep(obj)
            param.value = param.value.map(item => ({ label: item.value, value: item.key }))
            return [{ param, label: obj.key, value: obj.key }]
    }
    return []
}

/**
 * 深度定制组件
 * @param  nodeId 节点id, itemKey 当前变量key, children, onSelect
 * @returns 
 */
const SelectVar = forwardRef(({
    nodeId,
    findInputFile = false, // 只展示input节点file_image变量(视觉表单项使用)
    itemKey, multip = false, value = [], children, onSelect, onCheck, className = '' }, ref) => {
    const [open, setOpen] = useState(false)
    const { flow } = useFlowStore()
    const [select, setSelect] = useState(['', ''])

    const inputOpenRef = useRef(false)
    useImperativeHandle(ref, () => ({
        open(inputOpen) {
            inputOpenRef.current = !!inputOpen
            setOpen(true)
        }
    }));

    const getNodeDataByTemp = (temp) => {
        // const hasChild = temp.group_params.some(group =>
        //     group.params.some(param => param.global)
        // )
        const firstMenu = {
            id: temp.id,
            type: temp.type,
            name: temp.name,
            icon: <NodeLogo type={temp.type} colorStr={temp.name} />,
            desc: temp.description,
            tab: temp.tab?.value || '',
            data: temp.group_params
        }
        const children = getGlobalChild(firstMenu)
        firstMenu.data = children.length ? children : null
        return firstMenu
    }

    // vars
    const [vars, setVars] = useState([])
    const currentMenuRef = useRef(null)
    const getGlobalChild = (item) => {
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
                if (nodeId === item.id && param.key === itemKey) return
                if (!param.global) return
                // 处理code表达式
                if (param.global.indexOf('code') === 0) {
                    let result = isMatch(param, param.global.replace('code:', ''));
                    // 没值 key补
                    if (!result.length && param.key.startsWith('output')) {
                        result = [{
                            label: param.key,
                            value: param.key
                        }]
                    }
                    _vars = [..._vars, ...result]
                    // 特殊变量(getSpecialVar前端策略)
                } else if (param.global.startsWith('item')) {
                    const result = getSpecialVar(param, param.global, findInputFile)
                    _vars = [..._vars, ...result]
                } else if ((param.global === 'key' && nodeId !== item.id)
                    || (param.global === 'self' && nodeId === item.id)) {
                    _vars.push({
                        label: param.key,
                        value: param.key
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

        return _vars
    }

    const nodeTemps = useMemo(() => {
        // 如果节点数据未加载或组件未打开，返回空数组
        if (!flow?.nodes || !open) return [];

        return flow.nodes.reduce((processedNodes, node) => {
            let nodeData = node.data;

            // 特殊处理输入节点
            if (node.data.type === 'input') {
                // 输入节点，跳过自己
                if (node.data.id === nodeId) return processedNodes
                nodeData = processInputNode(node.data, findInputFile);
            }
            // 其他节点，跳过
            else if (findInputFile) {
                return processedNodes;
            }

            const newNode = getNodeDataByTemp(nodeData);
            newNode.data && processedNodes.push(newNode);
            return processedNodes;
        }, []);
    }, [open, flow.nodes]);

    /**
     * 根据文件类型过滤dialog_image_files文件变量
     * 限制findInputFileOnly为true时，过滤其他变量,只返回dialog_image_files文件变量
     */
    function processInputNode(inputNodeData, findInputFileOnly) {
        if (inputNodeData.tab.value === 'form_input') return inputNodeData;
        const processedData = cloneDeep(inputNodeData);
        let acceptType = 'all';

        const groupParam = processedData.group_params.find(group =>
            group.params.some(param => {
                if (param.key === "dialog_file_accept") {
                    acceptType = param.value;
                    return true;
                }
                return false;
            })
        );

        if (!groupParam) return processedData;

        // 根据文件类型过滤参数
        if (acceptType === 'file') {
            groupParam.params = groupParam.params.filter(param =>
                param.key !== 'dialog_image_files'
            );
        }
        // 如果只需要文件输入参数
        if (findInputFileOnly) {
            groupParam.params = groupParam.params.filter(param =>
                param.key === 'dialog_image_files'
            );
        }

        return processedData;
    }

    // 三级变量 预置问题
    const [questions, setQuestions] = useState([])
    const handleShowQuestions = (param) => {
        const values = param.value.filter(e => e.label)
        setQuestions(values.map(({ label, value }) => ({
            label,
            value: `${param.key}#${value}`
        })))
    }

    // clear
    useEffect(() => {
        if (!open) {
            setVars([])
            setQuestions([])
        }
    }, [open])

    // 级联checkbox
    const checkKeys = useMemo(() => {
        if (!onCheck) return {};

        // 工具函数：计算选中状态
        const getCheckStatus = (checkedCount, totalCount) => {
            if (totalCount === 0) return SelectStatus.Uncheck;
            if (checkedCount === totalCount) return SelectStatus.Check;
            if (checkedCount > 0) return SelectStatus.HalfCheck;
            return SelectStatus.Uncheck;
        };

        // 工具函数：处理三级菜单（如 preset_question）
        const handleNestedItems = (parentKey, items, valueSet) => {
            const keys = {};
            let checkedCount = 0;

            items.forEach((item, index) => {
                const itemKey = `${parentKey}#${item.value}`;
                const isChecked = valueSet.has(itemKey);
                keys[itemKey] = isChecked ? SelectStatus.Check : SelectStatus.Uncheck;
                if (isChecked) checkedCount++;
            });

            keys[parentKey] = getCheckStatus(checkedCount, items.length);
            return { keys, checkedCount };
        };

        const valueSet = new Set(value);

        // 遍历一级菜单
        return nodeTemps.reduce((acc, itemL1) => {
            let checkedCountL1 = 0;

            // 遍历二级菜单
            itemL1.data.forEach((itemL2) => {
                const keyL2 = `${itemL1.id}.${itemL2.value}`;

                if (itemL2.value === 'preset_question') {
                    // 处理三级菜单
                    const { keys: nestedKeys, checkedCount: checkedCountL2 } = handleNestedItems(
                        keyL2,
                        itemL2.param.value,
                        valueSet
                    );
                    Object.assign(acc, nestedKeys);
                    // if (checkedCountL2 === itemL2.param.value.length - 1) checkedCountL1++;
                    // question半选按选中计算
                    if (checkedCountL2 > 0) checkedCountL1++;
                } else {
                    // 处理普通二级菜单
                    const isChecked = valueSet.has(keyL2);
                    acc[keyL2] = isChecked ? SelectStatus.Check : SelectStatus.Uncheck;
                    if (isChecked) checkedCountL1++;
                }
            });

            // 更新一级菜单的选中状态
            acc[itemL1.id] = getCheckStatus(checkedCountL1, itemL1.data.length);
            return acc;
        }, {});
    }, [nodeTemps, value, onCheck]);


    const handleCheckClick = (checked, nodeId, variable = null) => {
        const currentNode = nodeTemps.find((item) => item.id === nodeId);
        if (!currentNode) return;

        // 工具函数：处理预设问题（preset_question）
        const handlePresetQuestion = (data, tasks) => {
            return data.param.value
                // .slice(0, -1) // 排除最后一个元素
                .map((item) => {
                    tasks.push({
                        node: currentNode,
                        variable: { ...item, value: `${data.value}#${item.value}` },
                    })
                });
        };

        // 工具函数：处理普通变量
        const handleNormalVariable = (item) => {
            return { node: currentNode, variable: item };
        };

        // 生成任务列表
        const tasks = [];
        if (variable && variable.value !== 'preset_question') {
            tasks.push(handleNormalVariable(variable))
        } else {
            currentNode.data?.map((item) =>
                item.param ? handlePresetQuestion(item, tasks) : variable?.value !== 'preset_question' && tasks.push(handleNormalVariable(item))
            ) || []
        }

        // 回调父组件
        onCheck(checked, tasks);
    };

    return <Select open={open} onOpenChange={setOpen}>
        <SelectTrigger
            onClick={() => inputOpenRef.current = false}
            showIcon={false}
            className={cname('group shrink min-w-0 p-0 h-auto data-[placeholder]:text-inherit border-none bg-transparent shadow-none outline-none focus:shadow-none focus:outline-none focus:ring-0', className)}>
            {children}
        </SelectTrigger>
        <SelectContent position="popper" avoidCollisions={false}>
            <div className="flex max-h-[360px] ">
                {/* 三级级联菜单 */}
                <div className="w-36 border-l first:border-none overflow-y-auto  scrollbar-hide">
                    {nodeTemps.map(item =>
                        <div
                            className={`${select[0] === item.id && 'bg-[#EBF0FF]'} relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50`}
                            onMouseEnter={() => {
                                setSelect([item.id, ''])
                                currentMenuRef.current = item;
                                setVars(item.data)
                                setQuestions([])
                            }}
                        >
                            {onCheck && <Checkbox checked={checkKeys[item.id]} onCheckedChange={(bln) => handleCheckClick(bln, item.id)} className="mr-1" />}
                            {item.icon}
                            <span className="w-28 overflow-hidden text-ellipsis ml-2">{item.name}</span>
                            <ChevronRight className="size-4" />
                        </div>
                    )}
                </div>
                {!!vars.length && <div className="w-36 border-l first:border-none overflow-y-auto scrollbar-hide">
                    {vars.map(v =>
                        <div
                            className={`${select[1] === v.value && 'bg-[#EBF0FF]'} relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50`}
                            onClick={() => {
                                if (v.param) return
                                onSelect(currentMenuRef.current, v, inputOpenRef.current)
                                !multip && setOpen(false)
                            }}
                            onMouseEnter={() => {
                                v.param ? handleShowQuestions(v.param) : setQuestions([])
                                setSelect((old) => [old[0], v.value])
                            }}>
                            {onCheck && <Checkbox
                                checked={checkKeys[`${currentMenuRef.current.id}.${v.value}`]}
                                className="mr-1"
                                onCheckedChange={(bln) => handleCheckClick(bln, currentMenuRef.current.id, v)}
                                onClick={e => e.stopPropagation()}
                            />}
                            <span className="w-28 overflow-hidden text-ellipsis">{v.label}</span>
                            {v.param && <ChevronRight className="size-4" />}
                            {/* {value.includes(`${currentMenuRef.current.id}.${v.value}`) && <Check size={14} />} */}
                        </div>
                    )}
                </div>}
                {
                    !!questions.length && <div className="w-44 border-l first:border-none">
                        {questions.map(q =>
                            <div
                                className="relative flex justify-between w-full select-none items-center rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                                onClick={() => {
                                    onSelect(currentMenuRef.current, q, inputOpenRef.current)
                                    !multip && setOpen(false)
                                }}>
                                {onCheck && <Checkbox
                                    checked={checkKeys[`${currentMenuRef.current.id}.${q.value}`]}
                                    className="mr-1"
                                    onCheckedChange={(bln) => handleCheckClick(bln, currentMenuRef.current.id, q)}
                                    onClick={e => e.stopPropagation()}
                                />}
                                <span className="w-full overflow-hidden text-ellipsis truncate">{q.label}</span>
                                {/* {value.includes(`${currentMenuRef.current.id}.${q.value}`) && <Check size={14} />} */}
                            </div>
                        )}
                    </div>
                }
            </div>
        </SelectContent>
    </Select>
});


export default SelectVar