import { Node } from "@xyflow/react";
import i18next from "i18next";
import { cloneDeep } from "lodash-es";
import { useEffect, useRef, useState } from "react";

// 节点名称自动命名
export function autoNodeName(nodes: Node[], name: string): string {
    let newName = name;
    let counter = 1;

    // 检查新名称是否已经存在于 nodes 中
    while (nodes.some(node => node.data.name === newName)) {
        counter++;
        const _name = name.replace(/\d+$/, '')
        newName = `${_name}${counter}`;
    }

    return newName;
}

// 在节点初始化时，将node中的模板变量替换为界面中对应的变量key
export function initNode(node) {
    const { id } = node;

    node.group_params.forEach(group => {
        group.params.forEach(param => {
            if (param.type === "var_textarea" && typeof param.value === "string") {
                // Replace expressions by inserting the node id dynamically
                param.value = param.value.replace(/{{#([^/]*\/)?(.*?)#}}/g, (match, prefix = '', expression) => {
                    if (param.varZh) {
                        param.varZh[`${prefix}${id}.${expression}`] = `${prefix}${expression}`
                    } else {
                        param.varZh = {
                            [`${prefix}${id}.${expression}`]: `${prefix}${expression}`
                        }
                    }
                    return `{{#${prefix}${id}.${expression}#}}`;
                });
            }
        });
    });

    return node;
}

// 工具节点tree
export function getToolTree(temp) {
    const children = temp.children.map(item => {
        return {
            id: '',
            tool_key: item.tool_key,
            type: 'tool',
            name: item.name,
            description: item.desc,
            group_params: [
                {
                    name: '工具参数',
                    params: item.api_params.map(el => ({
                        key: el.name,
                        label: el.name,
                        type: 'var_textarea',
                        test: "input",
                        desc: el.description,
                        required: el.required,
                        value: ''
                    }))
                },
                {
                    name: '输出',
                    params: [{
                        global: 'key',
                        key: 'output',
                        label: '输出变量',
                        type: 'var',
                        value: ''
                    }]
                }
            ]
        }
    })

    return {
        name: temp.name,
        children: children
    }
}

// 变量是否存在flow中
// 所有情况
// start_3ca7f.preset_question
// start_3ca7f.preset_question#uuid   type: "input_list"  value个数
// input_dee6e.text_input2    type: form   变量名 -> value[0].key
// llm_b12e5.output_start_d377c.chat_history   type:var && value是数组时  变量名 -> value[0].key
export function isVarInFlow(nodeId, nodes, varName, varNameCn) {
    if (!varName || typeof varName !== 'string') return ''
    const nodeName = nodes.find(node => node.id === nodeId).data.name
    const varNodeId = varName.match(/^([^.]+)/)[1]
    const res = nodes.some(node =>
        varNodeId === node.id ? node.data.group_params.some(group =>
            group.params.some(param => {
                if (param.type === 'input_list' && varName.indexOf('preset_question') !== -1) {
                    const questionId = varName.split('#')[1]
                    return param.value.some(item => item.key === questionId)
                } else if ((param.type === 'var' && Array.isArray(param.value) && param.value.length) || param.type === 'code_output') {
                    return param.value.some(item => `${node.id}.${item.key}` === varName)
                } else if (param.tab && param.tab !== node.data.tab.value) {
                    return false
                } else if (param.type === 'form') {
                    return param.value.some(item => {
                        if (item.multiple) return `${node.id}.${item.key}` === varName
                        return [`${node.id}.${item.key}`, `${node.id}.${item.file_content}`, `${node.id}.${item.file_path}`].includes(varName)
                    })
                } else {
                    return `${node.id}.${param.key}` === varName
                }
            })
        ) : false
    )
    return res ? '' : i18next.t('nodeErrorMessage', { ns: 'flow', nodeName, varNameCn })
}

/**
 * 并行节点判断
 * // 测速数据
    var a = [
        { branch: "0_0_0", nodeId: "input_28f7a" },
        { branch: "0_0_0_0", nodeId: "input_6d972" },
        { branch: "0_0_0_1", nodeId: "input_75275" },
        { branch: "0_0_1", nodeId: "input_6bf08" },
        { branch: "0_1", nodeId: "input_4f5cc" } // 直接分支自 0
    ];

    var b = [
        { branch: "0_0", nodeId: "output_b808c" }
    ];
 */
export function findParallelNodes(a, b) {
    const result = [];
    const parents = b.sort((a, b) => a.branch.length - b.branch.length);

    for (let i = 0; i < a.length; i++) {
        const branch1 = a[i].branch;
        const parentBranch1 = branch1.split('_').slice(0, -1).join('_');
        for (let j = i + 1; j < a.length; j++) {
            const branch2 = a[j].branch;

            // 是否同一个分支
            if (branch1.startsWith(branch2) || branch2.startsWith(branch1)) {
                continue
            }

            // 获取父分支
            const parentBranch2 = branch2.split('_').slice(0, -1).join('_');

            // 检查父分支相同 & 节点不属于 b 的分支
            const isSameParent = parentBranch1 === parentBranch2;
            if (isSameParent) {
                const isUnderBBranch = parents.some(node =>
                    node.branch === parentBranch1
                );
                if (isUnderBBranch) {
                    continue
                }
                result.push(a[i].nodeId, a[j].nodeId);
            }

            // 不属于同一个父分支节点
            const isUnderBBranch = parents.some(node =>
                branch1.startsWith(node.branch) && branch2.startsWith(node.branch)
            );
            if (isUnderBBranch) {
                continue
            }
            result.push(a[i].nodeId, a[j].nodeId);
        }
    }

    // 去重并返回结果
    return [...new Set(result)];
}

/**
 * 复制粘贴节点
 * @param dom 事件绑定 dom
 * @param lastSelection 被复制对象
 * @param paste 粘贴时间回调，参数（克隆的lastSelection，鼠标当前坐标）
 * @param deps 依赖
 */
export function useCopyPasteNode(dom, lastSelection, paste, del, deps) {
    const position = useRef({ x: 0, y: 0 });
    const [lastCopiedSelection, setLastCopiedSelection] = useState(null);

    useEffect(() => {
        if (!dom) return
        const onKeyDown = (event: KeyboardEvent) => {
            console.log('event.target :>> ', event.target);
            if (!dom.contains(event.target)) return
            if (['INPUT', 'TEXTAREA'].includes(event.target.tagName)) return // 排除输入框内复制粘贴
            if (
                event.target instanceof HTMLInputElement ||
                (event.target instanceof HTMLElement && event.target.isContentEditable)
            ) return

            if (
                (event.ctrlKey || event.metaKey) &&
                event.key === "c" &&
                lastSelection
            ) {
                event.preventDefault();
                setLastCopiedSelection(cloneDeep(lastSelection));
            } else if (
                (event.ctrlKey || event.metaKey) &&
                event.key === "v" &&
                lastCopiedSelection
            ) {
                event.preventDefault();
                paste(lastCopiedSelection, position.current)
            } else if (event.key === 'Delete' && lastSelection) {
                del(lastSelection)
            }
        };
        const handleMouseMove = (event) => {
            position.current = { x: event.clientX, y: event.clientY };
        };

        document.addEventListener("keydown", onKeyDown);
        document.addEventListener("mousemove", handleMouseMove);

        return () => {
            document?.removeEventListener("keydown", onKeyDown);
            document?.removeEventListener("mousemove", handleMouseMove);
        };
    }, [dom, lastSelection, lastCopiedSelection, ...deps]);
}


// 过滤无用连线
export function filterUselessFlow(nodes, edges) {
    return edges.filter(edge => {
        const sourceNode = nodes.find(node => node.id === edge.source);
        const targetNode = nodes.find(node => node.id === edge.target);
        return sourceNode && targetNode;
    })
}