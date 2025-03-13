import { generateUUID } from "@/components/bs-ui/utils";

// 历史版本工作流转换脚本(最新v1)
export const flowVersionCompatible = (flow) => {

    flow.nodes.forEach((node) => {

        switch (node.data.type) {
            case 'start': comptibleStart(node.data); break;
            case 'input': comptibleInput(node.data); break;
            case 'agent': comptibleAgent(node.data); break;
        }
    })
    return flow
}

const comptibleStart = (node) => {
    if (!node.v) {
        node.group_params[1].params[2].global = 'item:input_list'

        node.group_params[1].params[2].value = node.group_params[1].params[2].value.map((item) => ({
            key: generateUUID(6),
            value: item
        }))
        // TODO 历史使用过的预知问题变量替换

        node.v = 1
    }
}

const comptibleInput = (node) => {
    if (!node.v) {
        node.tab.value = node.tab.value === 'form' ? 'form_input' : 'dialog_input'
        node.tab.options[0].key = 'dialog_input'
        node.tab.options[1].key = 'form_input'
        node.group_params[0].params[0].tab = 'dialog_input'
        node.group_params[0].params[1].tab = 'form_input'

        node.group_params[0].params[1].global = 'item:form_input'

        let i = 0
        node.group_params[0].params[1].value = node.group_params[0].params[1].value.map((item) => {
            if (item.type === 'file') {
                i++
                return {
                    ...item,
                    file_content: 'file_content' + i,
                    file_path: 'file_path' + i,
                    multiple: item.multi
                }
            }
            return item
        })

        node.v = 1
    }
}

const comptibleAgent = (node) => {
    if (!node.v && node.group_params[1].params[0].type === 'bisheng_model') {
        node.group_params[1].params[0].type = 'agent_model'
        node.v = 1
    }
}