import { visit } from 'unist-util-visit';

export const remarkCitationPlugin = () => {
    return (tree) => {
        visit(tree, 'text', (node) => {
            if (typeof node.value === 'string') {
                const regex = /\[citation:(\d+)\]/g;
                // node.value = node.value.replace(regex, (match, number) => {
                //     // 将 [citation:number] 替换为一个自定义标记
                //     return `<citation>${number}</citation>`; // 标记为 "citation:number"
                // });
                if (regex.test(node.value)) {
                    node.name = 'citation'
                    node.data = {
                        hName: node.name,
                        hProperties: node.attributes,
                        ...node.data,
                    };
                    return node;
                }
            }
        });
    };
};