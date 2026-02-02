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
            case 'knowledge_retriever': comptibleKnowledgeRetriever(node.data); break;
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
            label: "true",
            type: "metadata_filter",
            value: {},
        };
        knowledgeGroup.params.splice(knowledgeIndex + 1, 0, metadataFilterParam);

        // 构造高级检索配置参数
        const advancedParam = {
            key: "advanced_retrieval_switch",
            label: "true",
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
        knowledgeGroup.params.splice(knowledgeIndex + 2, 0, advancedParam);

        node.v = 2;
    }
    if (node.v == 2) {
        const knowledgeGroup = node.group_params[0];
        const metadataFilterExists = knowledgeGroup.params.some(p => p.key === 'metadata_filter');
        if (!metadataFilterExists) {
            const knowledgeIndex = knowledgeGroup.params.findIndex(p => p.key === 'knowledge');
            const metadataFilterParam = {
                key: "metadata_filter",
                label: "true",
                type: "metadata_filter",
                value: {},
            };
            knowledgeGroup.params.splice(knowledgeIndex + 1, 0, metadataFilterParam);
        }
        node.v = 3;
    }
}

const comptibleKnowledgeRetriever = (node) => {
    // 初始化版本（无v字段视为v1）
    if (!node.v) {
        node.v = 1;
    }

    // v1 → v2：确保元数据过滤参数存在
    if (node.v == 1) {
        const knowledgeGroup = node.group_params[0];
        // 检查metadata_filter参数是否缺失
        const metadataFilterExists = knowledgeGroup.params.some(p => p.key === 'metadata_filter');

        if (!metadataFilterExists) {
            // 找到knowledge参数的位置，在其后插入元数据过滤参数
            const knowledgeIndex = knowledgeGroup.params.findIndex(p => p.key === 'knowledge');
            const metadataFilterParam = {
                key: "metadata_filter",
                label: "true",
                type: "metadata_filter",
                value: {},
            };
            knowledgeGroup.params.splice(knowledgeIndex + 1, 0, metadataFilterParam);
        }

        // 升级版本号为v2
        node.v = 2;
    }
};


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
    if (node.v == 1) {
        node.group_params[1].params.unshift({
            "key": "user_info",
            "global": "key",
            "label": "true",
            "type": "var",
            "value": "",
        })

        node.v = 2
    }
    if (node.v == 2) {
        node.group_params[1].params.push({
            "key": "custom_variables",
            "label": "true",
            "global": "item:input_list",
            "type": "global_var",
            "value": [],
            "help": "true"
        })
        node.v = 3
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
            label: "true",
            type: "var",
            tab: "dialog_input"
        })

        node.group_params[0].params.push({
            key: "dialog_files_content_size",
            label: "true",
            type: "char_number",
            min: 0,
            value: 15000,
            tab: "dialog_input"
        })

        node.group_params[0].params.push({
            key: "dialog_file_accept",
            label: "true",
            type: "select_fileaccept",
            value: "all",
            tab: "dialog_input"
        })

        node.group_params[0].params.push({
            key: "dialog_image_files",
            global: "key",
            label: "true",
            type: "var",
            tab: "dialog_input",
            help: "true"
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
    // 2 => 3
    if (node.v == 2) {
        // 1. 提取 v2 中的原始参数
        const oldParams = node.group_params[0].params;
        const findParam = (key) => oldParams.find(p => p.key === key);

        const userInput = findParam('user_input');
        const filesContent = findParam('dialog_files_content');
        const filesSize = findParam('dialog_files_content_size');
        const fileAccept = findParam('dialog_file_accept');
        const imageFiles = findParam('dialog_image_files');
        const formInput = findParam('form_input');
        formInput.value = []

        // 2. 重新构造 group_params 数组，确保顺序和 v3 一致
        node.group_params = [
            // group：接收文本
            {
                "name": "接收文本",
                "params": [userInput]
            },
            // group：文件配置 (inputfile)
            {
                "name": "",
                "groupKey": "inputfile",
                "params": [
                    {
                        "groupTitle": true,
                        "key": "user_input_file",
                        "tab": "dialog_input",
                        "value": true
                    },
                    {
                        "key": "file_parse_mode",
                        "type": "select_parsemode",
                        "tab": "dialog_input",
                        "value": "extract_text"
                    },
                    {
                        ...filesContent,
                        "global": "item:group_input_file" // v3 中变更为 item:group_input_file
                    },
                    filesSize,
                    fileAccept,
                    {
                        ...imageFiles,
                        "global": "item:group_input_file" // v3 中变更为 item:group_input_file
                    },
                    {
                        "key": "dialog_file_path",
                        "global": "item:group_input_file",
                        "label": "true",
                        "type": "var",
                        "tab": "dialog_input",
                        "help": "true"
                    }
                ]
            },
            // group：推荐问题配置 (custom)
            {
                "name": "",
                "groupKey": "custom",
                "params": [
                    {
                        "groupTitle": true,
                        "key": "recommended_questions_flag",
                        "label": "true",
                        "hidden": "true",
                        "tab": "dialog_input",
                        "help": "true",
                        "value": false
                    },
                    {
                        "key": "recommended_llm",
                        "label": "true",
                        "type": "bisheng_model",
                        "tab": "dialog_input",
                        "value": "",
                        "required": true,
                        "placeholder": "true"
                    },
                    {
                        "key": "recommended_system_prompt",
                        "label": "true",
                        "tab": "dialog_input",
                        "type": "var_textarea",
                        "value": "true",
                        "required": true
                    },
                    {
                        "key": "recommended_history_num",
                        "label": "true",
                        "type": "slide",
                        "tab": "dialog_input",
                        "help": "true",
                        "scope": [1, 10],
                        "step": 1,
                        "value": 2
                    }
                ]
            },
            // group：表单输入
            {
                "name": "",
                "params": [formInput]
            }
        ];

        node.v = 3;
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
            label: "true",
            type: "image_prompt",
            value: "",
            help: "true"
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
            label: "true",
            type: "image_prompt",
            value: [],
            help: "true"
        })

        node.v = 2
    }
}