import { getAssistantModelConfig, getLlmDefaultModel } from "@/controllers/API/finetune";
import { copyReportTemplate } from "@/controllers/API/workflow";
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
export function initNode(node, nds, t) {
    const { id } = node;
    if (node.type === "tool") {
        if (node.is_preset) {
            // 国际化工具节点
            node.name = t(`tools.${node.tool_key}.name`, { ns: 'tool' })
            node.description = t(`tools.${node.tool_key}.desc`, { ns: 'tool' })
            return node;
        }
        return node;
    }
    const nodeMap = new Map(nds.map(n => [n.data.type, n.data]));
    node.group_params.forEach(group => {
        group.params.forEach(param => {
            if (param.type !== "var_textarea" || typeof param.value !== "string" || !param.value) {
                return;
            }

            const translationKey = `node.${node.type}.${param.key}.value`;
            param.value = t(translationKey);

            // Replace expressions by inserting the node id dynamically
            param.value = param.value.replace(/{{#([^/]*\/)?(.*?)#}}/g, (match, prefixMatch = '', expression) => {
                let targetId = id;
                let targetName = '';
                if (prefixMatch) {
                    const typePrefix = prefixMatch.replace('/', '');
                    const targetNode = nodeMap.get(typePrefix);

                    if (targetNode) {
                        targetId = targetNode.id;
                        targetName = `${targetNode.name}/`;
                    } else {
                        return match;
                    }
                }

                param.varZh = param.varZh ?? {};
                param.varZh[`${targetId}.${expression}`] = `${targetName}${expression}`;

                return `{{#${targetId}.${expression}#}}`;
            });
        });
    });

    const newName = autoNodeName(nds, t(`node.${node.type}.name`))
    node.name = newName
    node.description = t(`node.${node.type}.description`)
    return node;
}

// 工具节点tree
export function getToolTree(temp) {
    const children = temp.children.map(item => {
        return {
            id: item.id,
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
        is_preset: temp.is_preset,
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
                if (param.key === 'custom_variables') {
                    const questionId = varName.split('#')[1]
                    const quwstionStr = varNameCn?.split('/')[1] || ''
                    return param.value.some(item => item.key === questionId && item.label === quwstionStr)
                } else if (param.type === 'input_list' && varName.indexOf('preset_question') !== -1) {
                    const questionId = varName.split('#')[1]
                    const quwstionStr = varNameCn?.split('/')[1] || ''
                    return param.value.some(item => item.key === questionId && item.value === quwstionStr) // id and name 必须一致
                } else if ((param.type === 'var' && Array.isArray(param.value) && param.value.length) || param.type === 'code_output') {
                    return param.value.some(item => `${node.id}.${item.key}` === varName)
                } else if (param.tab && param.tab !== node.data.tab.value) {
                    return false
                } else if (param.type === 'form') {
                    return param.value.some(item => {
                        // 文本类型
                        if (item.type === 'text' && `${node.id}.${item.key}` !== varName) return false
                        // if (item.multiple) return `${node.id}.${item.key}` === varName
                        // 文件类型
                        const vars = [`${node.id}.${item.key}`, `${node.id}.${item.file_content}`, `${node.id}.${item.file_path}`]
                        // 图片类型追加校验变量
                        item.file_type !== 'file' && vars.push(`${node.id}.${item.image_file}`)
                        return vars.includes(varName)
                    })
                } else if (param.hidden) {
                    return false
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

// 导入工作流
export function importFlow() {
    return new Promise((resolve, reject) => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".json";
        input.onchange = (e: Event) => {
            if ((e.target as HTMLInputElement).files[0].type === "application/json") {
                const currentfile = (e.target as HTMLInputElement).files[0];
                currentfile.text().then(async (text) => {
                    try {
                        let flow = JSON.parse(text);

                        if (!flow || !Array.isArray(flow.nodes)) {
                            return reject("flow.nodes 不存在或不是数组");
                        }
                        // 使用 Promise.all 等待所有的 copyReportTemplate 完成
                        await Promise.all(flow.nodes.map(async (node) => {
                            await copyReportTemplate(node.data);
                        }));

                        // 夸环境模型自动更新为默认模型, 并清空知识库和工具
                        if (flow.source !== location.host) {
                            const [workflow, assistant] = await Promise.all([getLlmDefaultModel(), getAssistantModelConfig()])
                            const workflowModelId = workflow.model_id
                            const assistantModelId = assistant.llm_list.find(item => item.default).model_id
                            delete flow.source

                            flow.nodes.forEach(node => {
                                if (['rag', 'llm', 'agent', 'qa_retriever'].includes(node.data.type)) {
                                    node.data.group_params.forEach(group =>
                                        group.params.forEach(param => {
                                            if (param.type === 'bisheng_model') {
                                                param.value = workflowModelId
                                            } else if (param.type === 'agent_model') {
                                                param.value = assistantModelId
                                            } else if (param.type === 'knowledge_select_multi' && param.value.type !== 'tmp') {
                                                param.value.value = []
                                            } else if (param.type === 'qa_select_multi') {
                                                param.value = []
                                            } else if (param.type === 'add_tool') {
                                                param.value = []
                                            }
                                        })
                                    )
                                }
                            })
                        }

                        resolve(flow)
                    } catch (error) {
                        reject(error)
                    }
                });
            }
        };
        input.onerror = reject
        input.click();
    })
}

// 计算复制后的节点目标位置
export function calculatePosition(nodes, position) {
    if (nodes.some(node => node.position.x === position.x && node.position.y === position.y)) {
        return calculatePosition(nodes, { x: position.x + 50, y: position.y + 50 })
    }
    return position
}

/**
 * Update node Preset Questions  or node name
 * use for selet textarea
 */
const createReg = (id) => [
    new RegExp(`^[\\w_]+\\.([\\w_]+)?preset_question#${id}$`),
    new RegExp(`^[\\w_]+\\.([\\w_]+)?preset_question_${id}$`)
]
export function updateVariableName(paramItem, questions) {
    const { node, question } = questions

    if (question) {
        const [regWell, regUnderline] = createReg(question.id)

        return Object.keys(paramItem.varZh).reduce((change, _key) => {
            if (regWell.test(_key)) {
                paramItem.varZh[_key] = paramItem.varZh[_key].replace(/\/[^\/]+$/, '/' + question.name)
                return true
            } else if (regUnderline.test(_key)) {
                paramItem.varZh[_key] = paramItem.varZh[_key].replace(/_[^_]+$/, '_' + question.name)
                return true
            }
            return change
        }, false)
    }

    if (node) { // output has no node name, so no need to update
        return Object.keys(paramItem.varZh).reduce((change, _key) => {
            if (_key.startsWith(node.id)) {
                paramItem.varZh[_key] = paramItem.varZh[_key].replace(/^[^\/]+\//, node.name + '/')
                return true
            }
            return change
        }, false)
    }
    return false
}

/**
 * Update node Preset Questions  or node name
 * use for code
 */
export function updateVariableNameByCode(paramItem, questions) {
    const { node, question } = questions

    if (question) {
        const [regWell, regUnderline] = createReg(question.id)
        const newItems = paramItem.value.reduce((change, item) => {
            if (regWell.test(item.value)) {
                item.label = item.label.replace(/\/[^\/]+$/, '/' + question.name)
                return paramItem.value
            } else if (regUnderline.test(item.value)) {
                item.label = item.label.replace(/_[^_]+$/, '_' + question.name)
                return paramItem.value
            }
            return change
        }, null)
        return newItems && [...newItems]
    }

    if (node) { // output has no node name, so no need to update
        const newItems = paramItem.value.map(item => {
            if (item.value.startsWith(node.id)) {
                item.label = item.label.replace(/^[^\/]+\//, node.name + '/')
            }
            return item
        }, null)
        return newItems && [...newItems]
    }
    return null
}


/**
 * Update node Preset Questions  or node name
 * use for condition
 */
export function updateVariableNameByCondition(paramItem, questions) {
    const { node, question } = questions

    if (question) {
        const [regWell, regUnderline] = createReg(question.id)

        const replaceLabel = (conditionm, key, label) => {
            if (regWell.test(conditionm[key])) {
                conditionm[label] = conditionm[label].replace(/\/[^\/]+$/, '/' + question.name)
            } else if (regUnderline.test(conditionm[key])) {
                conditionm[label] = conditionm[label].replace(/_[^_]+$/, '_' + question.name)
            }
        }

        return paramItem.value.map((item) => {
            item.conditions.forEach(condition => {
                replaceLabel(condition, 'left_var', 'left_label')
                replaceLabel(condition, 'right_value', 'right_label')
            })

            return item
        })
    }

    if (node) { // output has no node name, so no need to update
        const replaceLabel = (conditionm, key, label) => {
            if (conditionm[key].startsWith(node.id)) {
                conditionm[label] = conditionm[label].replace(/^[^\/]+\//, node.name + '/')
                return paramItem.value
            }
        }

        return paramItem.value.map((item) => {
            item.conditions.forEach(condition => {
                replaceLabel(condition, 'left_var', 'left_label')
                replaceLabel(condition, 'right_value', 'right_label')
            })

            return item
        })
    }
    return null
}