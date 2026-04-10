import { visit } from 'unist-util-visit';

export const remarkCitationPlugin = () => {
    return (tree) => {
        visit(tree, 'text', (node) => {
            if (typeof node.value === 'string') {
                const regex = /(\[citation:(\d+)\]|\[citationref:([^\]]+)\])/g;
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
