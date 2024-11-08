import { Node } from "@xyflow/react";

// 节点名称自动命名
export function autoNodeName(nodes: Node[], name: string): string {
    let newName = name;
    let counter = 0;

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