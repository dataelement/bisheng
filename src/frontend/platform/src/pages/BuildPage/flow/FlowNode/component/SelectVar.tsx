import { Checkbox } from "@/components/bs-ui/checkBox";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import Tip from "@/components/bs-ui/tooltip/tip";
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
const getSpecialVar = ({ obj, group, onlyImg = false }) => {
    const type = obj.global
    
    switch (type) {
        case 'item:form_input':
            return obj.value.reduce((res, item) => {
                const { file_type, file_parse_mode } = item;
                // F038 (单选 + 变量联动): file_parse_mode is the option's mode array
                // ([extract] / [extract,ingest] / [keep_raw]); legacy string tolerated.
                // Expose by the unified rule: path always, image by upload type,
                // content when parsing, key (temp KB) when ingesting.
                const modes = Array.isArray(file_parse_mode)
                    ? file_parse_mode
                    : (file_parse_mode ? [file_parse_mode] : []);
                const isImageCapable = file_type === 'all' || file_type === 'image';
                const isParse = modes.includes('extract_text');
                const isIngest = modes.includes('ingest_to_temp_kb');

                const add = (propKey) => res.push({ label: item[propKey], value: item[propKey] });
                // 文本 / 下拉 use key
                if (['select', 'text'].includes(item.type)) {
                    !onlyImg && add('key')
                    return res
                }
                // 图片变量：上传类型含图片即暴露（不看策略）
                if (isImageCapable && item.image_file) {
                    add('image_file');
                }
                if (onlyImg) return res;
                // 解析结果（解析时）/ 临时库名（入库时）/ 文件路径（恒暴露）
                if (isParse && item.file_content) add('file_content');
                if (isIngest) add('key');
                if (item.file_path) add('file_path');

                return res;
            }, []);
        case 'item:input_list':
            if (!obj.value.length) return []
            if (!obj.value[0].value) return []
            const param = cloneDeep(obj)
            param.value = param.value.map(item => ({ label: item.label || item.value, value: item.key }))
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
    align = "left",
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
                if (nodeId === item.id && (
                    param.key.indexOf('output') === 0 ||
                    (param.key.indexOf('retrieved') === 0 && param.global.split('=')[0] !== 'self')
                )) return
                // 不能选自己(相同变量名视为self) param.key
                if (nodeId === item.id && param.key === itemKey) return
                if (!param.global) return
                // 处理code表达式
                if (param.global.indexOf('code') === 0) {
                    let result = isMatch(param, param.global.replace('code:', ''));
                    // 没值 key补
                    if (!result.length && (param.key.startsWith('output') || param.key.startsWith('retrieved'))) {
                        result = [{
                            label: param.key,
                            value: param.key
                        }]
                    }
                    _vars = [..._vars, ...result]
                    // 特殊变量(getSpecialVar前端策略)
                } else if (param.global.startsWith('item')) {
                    const result = getSpecialVar({ obj: param, onlyImg: findInputFile, group })
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
     * 处理输入节点数据
     * @param {Object} inputNodeData 原始节点数据
     * @param {Boolean} findInputFileOnly 是否仅返回文件变量
     */
    function processInputNode(inputNodeData, findInputFileOnly) {
        if (inputNodeData.tab.value === 'form_input') return inputNodeData;

        const processedData = cloneDeep(inputNodeData);

        // 1. Pre-extract 'dialog_file_accept' value for internal logic
        let acceptType = 'all';
        for (const group of processedData.group_params) {
            const acceptParam = group.params.find(p => p.key === 'dialog_file_accept');
            if (acceptParam) {
                acceptType = acceptParam.value;
                break;
            }
        }

        processedData.group_params.forEach(group => {
            // --- Logic for 'inputfile' group switch ---
            if (group.groupKey === 'inputfile') {
                const userInputFileParam = group.params.find(p => p.key === 'user_input_file');
                // If the file upload feature is disabled, clear the entire group
                if (userInputFileParam && userInputFileParam.value === false) {
                    group.params = [];
                    return;
                }
            }

            // F038 (单选 + 变量联动): dialog file_parse_mode is a single string
            // (extract_text / keep_raw); legacy map/array tolerated. Expose by the
            // unified rule: path always, image by upload type, content when parsing.
            const parseModeRaw = group.params.find(p => p.key === 'file_parse_mode')?.value;
            const dialogModes = typeof parseModeRaw === 'object' && parseModeRaw !== null
                ? (Array.isArray(parseModeRaw) ? parseModeRaw : Object.values(parseModeRaw))
                : (parseModeRaw ? [parseModeRaw] : []);
            const isExtract = dialogModes.includes('extract_text');

            group.params = group.params.filter(param => {
                // HIGHEST PRIORITY: If the parameter does NOT have 'global', keep it (no filtering)
                if (!Object.prototype.hasOwnProperty.call(param, 'global')) {
                    return true;
                }

                const { key } = param;

                // --- INTERNAL LOGIC: Specific to 'inputfile' group variables ---
                if (group.groupKey === 'inputfile') {
                    // Parsed text only when the strategy parses
                    if (key === 'dialog_files_content' && !isExtract) {
                        return false;
                    }
                    // Image variable only when the upload type allows images
                    if (key === 'dialog_image_files' && acceptType === 'file') {
                        return false;
                    }
                    // dialog_file_paths is always exposed (path 恒暴露) — never filtered
                }

                // --- GLOBAL FILTER: Only applies if findInputFileOnly is requested ---
                if (findInputFileOnly) {
                    // Only return dialog_image_files as the valid file variable
                    return key === 'dialog_image_files';
                }

                return true;
            });
        });

        // 3. Remove groups that are empty after filtering
        // processedData.group_params = processedData.group_params.filter(
        //     group => group.params.length > 0
        // );

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

                if (['preset_question', 'custom_variables'].includes(itemL2.value)) {
                    // 处理三级菜单
                    const { keys: nestedKeys, checkedCount: checkedCountL2 } = handleNestedItems(
                        keyL2,
                        itemL2.param.value.filter(e => e.label),
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
                    item.label && tasks.push({
                        node: currentNode,
                        variable: { ...item, value: `${data.label || data.value}#${item.value}` },
                    })
                });
        };

        // 工具函数：处理普通变量
        const handleNormalVariable = (item) => {
            return { node: currentNode, variable: item };
        };

        // 生成任务列表
        const tasks = [];
        // 全选
        if (!variable) {
            currentNode.data.forEach((item) => {
                if (item.param) {
                    handlePresetQuestion(item, tasks);
                } else {
                    tasks.push(handleNormalVariable(item));
                }
            });
        } else if (variable.param) {
            // 全选二级
            currentNode.data.some((item) => {
                if (item.param && variable.value === item.value) {
                    handlePresetQuestion(item, tasks);
                    return true
                }
            });
        } else {
            tasks.push(handleNormalVariable(variable));
        }

        // 回调父组件
        onCheck(checked, tasks);
    };

    return <Select open={open} onOpenChange={setOpen} >
        <SelectTrigger
            onClick={() => inputOpenRef.current = false}
            showIcon={false}
            className={cname('group shrink min-w-0 p-0 h-auto data-[placeholder]:text-inherit border-none bg-transparent shadow-none outline-none focus:shadow-none focus:outline-none focus:ring-0', className)}>
            {children}
        </SelectTrigger>
        <SelectContent position="popper" avoidCollisions={false} className={align === 'left' ? "overflow-auto -translate-x-28" : 'overflow-auto'} >
            <div className="flex max-h-[360px] ">
                {/* 三级级联菜单 */}
                <div className="w-36 min-w-36 border-l first:border-none overflow-y-auto  scrollbar-hide">
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
                {!!vars.length && <div className="w-36 min-w-36 border-l first:border-none overflow-y-auto scrollbar-hide">
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
                    !!questions.length && <div className="w-44 min-w-36 border-l first:border-none">
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
                                <Tip content={q.label.length > 7 && q.label} side={"top"} >
                                    <span className="w-full overflow-hidden text-ellipsis truncate">{q.label}</span>
                                </Tip>
                                {/* {value.includes(`${currentMenuRef.current.id}.${q.value}`) && <Check size={14} />} */}
                            </div>
                        )}
                    </div>
                }
            </div>
        </SelectContent>
    </Select >
});


export default SelectVar