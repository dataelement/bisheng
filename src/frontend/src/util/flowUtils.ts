import { Node } from "@xyflow/react";

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

// 节点初始化
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