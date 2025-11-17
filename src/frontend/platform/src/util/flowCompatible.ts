import { generateUUID } from "@/components/bs-ui/utils";

// 历史版本工作流转换脚本
export const flowVersionCompatible = (flow) => {
    flow.nodes.forEach((node) => {

        switch (node.data.type) {
            case 'start': comptibleStart(node.data); break;
            case 'input': comptibleInput(node.data); break;
            case 'agent': comptibleAgent(node.data); break;
            case 'output': comptibleOutput(node.data); break;
            case 'llm': comptibleLLM(node.data); break;
            case 'rag': comptibleRag(node.data); break;
        }
    })
    return flow
}
const comptibleRag = (node) => {  
    if (!node.v) {
        node.v = 1
    }
    if (node.v == 1) {
        const knowledgeGroup = node.group_params[0];
        // 先读取旧参数值，再进行移除，避免丢失数据
        const oldUserAuthParam = knowledgeGroup.params.find(p => p.key === 'user_auth');
        const oldMaxChunkSizeParam = knowledgeGroup.params.find(p => p.key === 'max_chunk_size');

        // 移除旧的拆散参数
        knowledgeGroup.params = knowledgeGroup.params.filter(param =>
            !['user_auth', 'max_chunk_size'].includes(param.key)
        );

        const knowledgeIndex = knowledgeGroup.params.findIndex(p => p.key === 'knowledge');
         // 添加元数据过滤参数
        const metadataFilterParam = {
            key: "metadata_filter",
            label: "元数据过滤",
            type: "metadata_filter",
            value: {},
        };
        knowledgeGroup.params.splice(knowledgeIndex + 1, 0, metadataFilterParam);

        // 构造高级检索配置参数
        const advancedParam = {
            key: "advanced_retrieval_switch",
            label: "高级检索配置",
            type: "search_switch",
            value: {
                keyword_weight: 0.5,
                vector_weight: 0.5,
                user_auth: false,
                search_switch: true,
                rerank_flag: false,
                rerank_model: "",
                max_chunk_size: 15000,
            }
        };
        // 从 v1 的 user_auth 与 max_chunk_size 继承值到新参数
        if (oldUserAuthParam) {
            advancedParam.value.user_auth = oldUserAuthParam.value;
        }
        if (oldMaxChunkSizeParam) {
            advancedParam.value.max_chunk_size = oldMaxChunkSizeParam.value;
        }
        knowledgeGroup.params.splice(knowledgeIndex + 1, 0, advancedParam);

        node.v = 2;
    }
    if(node.v == 2){
         const knowledgeGroup = node.group_params[0];
        const metadataFilterExists = knowledgeGroup.params.some(p => p.key === 'metadata_filter');
        if (!metadataFilterExists) {
            const knowledgeIndex = knowledgeGroup.params.findIndex(p => p.key === 'knowledge');
            const metadataFilterParam = {
                key: "metadata_filter",
                label: "元数据过滤",
                type: "metadata_filter",
                value: {},
            };
            knowledgeGroup.params.splice(knowledgeIndex + 1, 0, metadataFilterParam);
        }
        node.v = 3;
    }
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
    } else if (node.v == 1) {
        node.group_params[1].params.unshift({
            "key": "user_info",
            "global": "key",
            "label": "用户信息",
            "type": "var",
            "value": "",
        })

        node.v = 2
    }
}


const comptibleInput = (node) => {
    // 0 => 1
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
    // 1 => 2
    if (node.v == 1) {
        node.group_params[0].params.push({
            key: "dialog_files_content",
            global: "key",
            label: "上传文件内容",
            type: "var",
            tab: "dialog_input"
        })

        node.group_params[0].params.push({
            key: "dialog_files_content_size",
            label: "文件内容长度上限",
            type: "char_number",
            min: 0,
            value: 15000,
            tab: "dialog_input"
        })

        node.group_params[0].params.push({
            key: "dialog_file_accept",
            label: "上传文件类型",
            type: "select_fileaccept",
            value: "all",
            tab: "dialog_input"
        })

        node.group_params[0].params.push({
            key: "dialog_image_files",
            global: "key",
            label: "上传图片文件",
            type: "var",
            tab: "dialog_input",
            help: "提取上传文件中的图片文件，当助手或大模型节点使用多模态大模型时，可传入此图片。"
        })

        // 兼容文件类型
        const formInput = node.group_params[0].params.find(item => item.key === 'form_input')
        formInput.value = formInput.value.map((item, index) => {
            if (item.type === 'file') {
                item.file_type = 'all'
                item.file_content_size = 15000
                item.image_file = 'image_file' + (index || '')
                return item
            }
            return item
        })
        node.v = 2
    }
}


const comptibleAgent = (node) => {
    if (!node.v) {
        if (node.group_params[1].params[0].type === 'bisheng_model') {
            node.group_params[1].params[0].type = 'agent_model'
        }
        node.v = 1
    }

    if (node.v == 1) {
        node.group_params[2].params.push({
            key: "image_prompt",
            label: "视觉",
            type: "image_prompt",
            value: "",
            help: "当使用多模态大模型时，可通过此功能传入图片，结合图像内容进行问答"
        })

        node.v = 2
    }
}


const comptibleOutput = (node) => {
    if (!node.v) {
        node.v = 1
    }
    if (node.v == 1) {
        node.group_params[0].params[0].key = 'message'
        node.group_params[0].params[0].global = 'key'

        node.v = 2
    }
}


const comptibleLLM = (node) => {
    if (!node.v) {
        node.v = 1
    }

    if (node.v == 1) {

        node.group_params[2].params.push({
            key: "image_prompt",
            label: "视觉",
            type: "image_prompt",
            value: [],
            help: "当使用多模态大模型时，可通过此功能传入图片，结合图像内容进行问答"
        })

        node.v = 2
    }
}