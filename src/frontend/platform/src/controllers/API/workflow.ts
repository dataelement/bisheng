import { WorkFlow } from "@/types/flow";
import i18next from "i18next";
import axios from "../request";

/**
 * 获取工作流节点模板s
 */
export const getWorkflowNodeTemplate = async (): Promise<any[]> => {
    return new Promise(res => setTimeout(() => {
        res(i18next.language === 'en' ? workflowTemplateEN : workflowTemplate)
    }, 100));
}

/**
 * 获取某工作流报告模板信息
 */
export const getWorkflowReportTemplate = async (key: string): Promise<any> => {
    return await axios.get(`/api/v1/workflow/report/file?version_key=${key}`);
}

/**
 * 创建工作流
 */
export const createWorkflowApi = async (name, desc, url, flow): Promise<any> => {
    if (url) {
        // logo保存相对路径
        url = url.replace('/bisheng', '')
    }
    const data = flow || {}
    return await axios.post("/api/v1/workflow/create", {
        ...data,
        name,
        description: desc,
        logo: url
    });
}

/**
 * 保存工作流
 */
export const saveWorkflow = async (versionId: number, data: WorkFlow): Promise<any> => {
    if (data.logo) {
        // logo保存相对路径
        data.logo = data.logo.replace('/bisheng', '')
    }
    return await axios.put(`/api/v1/workflow/versions/${versionId}`, data);
}

/** 上线工作流 & 修改信息 
 * status: 2 上线 1 下线
*/
export const onlineWorkflow = async (flow, status = ''): Promise<any> => {
    const { name, description, logo } = flow
    const data = { name, description, logo: logo && logo.match(/(icon.*)\?/)?.[1] }
    if (status) {
        data['status'] = status
    }
    return await axios.patch(`/api/v1/workflow/update/${flow.id}`, data);
}

/**
 * 上线指定版本工作流
 */
export const onlineWorkflowApi = async (data: { flow_id, version_id, status }) => {
    return await axios.patch(`/api/v1/workflow/status`, data);
};

/**
 * 单节点运行
 * 
 */
export const runWorkflowNodeApi = async (node_input, data): Promise<any> => {
    return await axios.post(`/api/v1/workflow/run_once`, {
        node_input, node_data: {
            id: data.id,
            data,
        }
    });
}

/**
 * 复制报告模板
 */
export const copyReportTemplate = async (nodeData): Promise<any> => {
    // console.log('nodeData :>> ', nodeData);
    if (nodeData.type === 'report') {
        const { version_key } = nodeData.group_params[0].params[0].value
        if (version_key) {
            return axios.post(`/api/v1/workflow/report/copy`, {
                version_key
            }).then(res => {
                nodeData.group_params[0].params[0].value.version_key = res.version_key
                console.warn('REPORT:使用旧KEY :>> ', version_key);
                console.warn('REPORT:获取新KEY :>> ', res.version_key);
            })
        }
    }
    return Promise.resolve('ok')
}

/**
 * 工作流节点模板
 */
const workflowTemplate = [
    {
        "id": "start_xxx",
        "name": "开始",
        "description": "工作流运行的起始节点。",
        "type": "start",
        "v": "1",
        "group_params": [
            {
                "name": "开场引导",
                "params": [
                    {
                        "key": "guide_word",
                        "label": "开场白",
                        "value": "",
                        "type": "textarea",
                        "placeholder": "每次工作流开始执行时向用户发送此消息，支持 Markdown 格式，为空时不发送。"
                    },
                    {
                        "key": "guide_question",
                        "label": "引导问题",
                        "value": [],
                        "type": "input_list",
                        "placeholder": "请输入引导问题",
                        "help": "为用户提供推荐问题，引导用户输入，超过3个时将随机选取3个。"
                    }
                ]
            },
            {
                "name": "全局变量",
                "params": [
                    {
                        "key": "user_info",
                        "global": "key",
                        "label": "用户信息",
                        "type": "var",
                        "value": ""
                    },
                    {
                        "key": "current_time",
                        "global": "key",
                        "label": "当前时间",
                        "type": "var",
                        "value": ""
                    },
                    {
                        "key": "chat_history",
                        "global": "key",
                        "type": "chat_history_num",
                        "value": 10
                    },
                    {
                        "key": "preset_question",
                        "label": "预置问题列表",
                        "global": "item:input_list",
                        "type": "input_list",
                        "value": [],
                        "placeholder": "输入批量预置问题",
                        "help": "适合文档审核、报告生成等场景，利用提前预置的问题批量进行 RAG 问答。"
                    }
                ]
            }
        ]
    },
    {
        "id": "input_xxx",
        "name": "输入",
        "description": "接收用户在会话页面的输入，支持 2 种形式：对话框输入，表单输入。",
        "type": "input",
        "v": "2",
        "tab": {
            "value": "dialog_input",
            "options": [
                {
                    "label": "对话框输入",
                    "key": "dialog_input",
                    "help": "接收用户从对话框输入的内容。"
                },
                {
                    "label": "表单输入",
                    "key": "form_input",
                    "help": "将会在用户会话界面弹出一个表单，接收用户从表单提交的内容。"
                }
            ]
        },
        "group_params": [
            {
                "name": "",
                "params": [
                    {
                        "key": "user_input",
                        "global": "key",
                        "label": "输入文本内容",
                        "type": "var",
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_files_content",
                        "global": "key",
                        "label": "上传文件内容",
                        "type": "var",
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_files_content_size",
                        "label": "文件内容长度上限",
                        "type": "char_number",
                        "min": 0,
                        "value": 15000,
                        "tab": "dialog_input"
                    },
                    {
                        "key": "is_allow_upload",
                        "label": "允许上传文件",
                        "type": "switch",
                        "tab": "dialog_input",
                        "help": "控制会话中是否允许上传文件",
                        "value": true
                    },
                    {
                        "key": "dialog_file_accept",
                        "label": "上传文件类型",
                        "type": "select_fileaccept",
                        "value": ['file', 'audio', 'image'],
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_image_files",
                        "global": "key",
                        "label": "上传图片文件",
                        "type": "var",
                        "tab": "dialog_input",
                        "help": "提取上传文件中的图片文件，当助手或大模型节点使用多模态大模型时，可传入此图片。"
                    },
                    {
                        "key": "dialog_audio_files",
                        "global": "key",
                        "label": "上传音频文件",
                        "type": "var",
                        "tab": "dialog_input",
                        "help": "提取上传文件中的音频文件，当助手或大模型节点使用多模态大模型时，可传入此图片。"
                    },
                    {
                        "key": "form_input",
                        "global": "item:form_input",
                        "label": "+ 添加表单项",
                        "type": "form",
                        "tab": "form_input",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "output_xxx",
        "name": "输出",
        "description": "可向用户发送消息，并且支持进行更丰富的交互，例如请求用户批准进行某项敏感操作、允许用户在模型输出内容的基础上直接修改并提交。",
        "type": "output",
        "v": "2",
        "group_params": [
            {
                "params": [
                    {
                        // TODO： 0522 KEY值改了 这里需要特别注意一下
                        "key": "message",
                        "label": "消息内容",
                        "global": "key",
                        "type": "var_textarea_file",
                        "required": true,
                        "placeholder": "输入需要发送给用户的消息，例如“接下来我将执行 XX 操作，请您确认”，“以下是我的初版草稿，您可以在其基础上进行修改”",
                        "value": {
                            "msg": "",
                            "files": []
                        }
                    },
                    {
                        "key": "output_result",
                        "label": "交互类型",
                        "global": "value.type=input",
                        "type": "output_form",
                        "required": true,
                        "value": {
                            "type": "",
                            "value": ""
                        },
                        "options": []
                    }
                ]
            }
        ]
    },
    {
        "id": "tts_xxx",
        "name": "文字转语音",
        "description": "调用大模型进行文字转语音。",
        "type": "tts",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "批处理变量",
                        "global": "self",
                        "type": "user_question",
                        "test": "var",
                        "value": [],
                        "required": true,
                        "linkage": "output",
                        "placeholder": "请选择批处理变量",
                        "help": "选择需要批处理的变量，将会多次运行本节点，每次运行时从选择的变量中取一项赋值给batch_variable进行处理。",
                    }
                ]
            },
            {
                "name": "模型设置",
                "params": [
                    {
                        "key": "model_id",
                        "label": "模型",
                        "type": "tts_model",
                        "value": "",
                        "required": true,
                        "placeholder": "请选择模型"
                    },
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "输出变量",
                        "help": "模型输出内容将会存储在该变量中。",
                        "type": "var",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "stt_xxx",
        "name": "语音转文字",
        "description": "调用大模型进行语音转文字。",
        "type": "stt",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "批处理变量",
                        "global": "self",
                        "type": "user_question",
                        "test": "var",
                        "value": [],
                        "required": true,
                        "linkage": "output",
                        "placeholder": "请选择批处理变量",
                        "help": "选择需要批处理的变量，将会多次运行本节点，每次运行时从选择的变量中取一项赋值给batch_variable进行处理。",
                    }
                ]
            },
            {
                "name": "模型设置",
                "params": [
                    {
                        "key": "model_id",
                        "label": "模型",
                        "type": "stt_model",
                        "value": "",
                        "required": true,
                        "placeholder": "请选择模型"
                    },
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "输出变量",
                        "help": "模型输出内容将会存储在该变量中。",
                        "type": "var",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "llm_xxx",
        "name": "大模型",
        "description": "调用大模型回答用户问题或者处理任务。",
        "type": "llm",
        "v": "3",
        "tab": {
            "value": "single",
            "options": [
                {
                    "label": "单次运行",
                    "key": "single"
                },
                {
                    "label": "批量运行",
                    "key": "batch"
                }
            ]
        },
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "批处理变量",
                        "global": "self",
                        "type": "user_question",
                        "test": "var",
                        "value": [],
                        "required": true,
                        "linkage": "output",
                        "placeholder": "请选择批处理变量",
                        "help": "选择需要批处理的变量，将会多次运行本节点，每次运行时从选择的变量中取一项赋值给batch_variable进行处理。",
                        "tab": "batch"
                    }
                ]
            },
            {
                "name": "模型设置",
                "params": [
                    {
                        "key": "model_id",
                        "label": "模型",
                        "type": "bisheng_model",
                        "value": "",
                        "required": true,
                        "placeholder": "请在模型管理中配置 LLM 模型"
                    },
                    {
                        "key": "temperature",
                        "label": "温度",
                        "type": "slide",
                        "scope": [
                            0,
                            2
                        ],
                        "step": 0.1,
                        "value": 0.7
                    },
                    {
                        "key": "enable_web_search",
                        "label": "联网搜索",
                        "type": "online_switch",
                        "help": "",
                        "value": false
                    },
                ]
            },
            {
                "name": "提示词",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "系统提示词",
                        "type": "var_textarea",
                        "test": "var",
                        "value": ""
                    },
                    {
                        "key": "user_prompt",
                        "label": "用户提示词",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "required": true
                    },
                    {
                        "key": "image_prompt",
                        "label": "视觉",
                        "type": "image_prompt",
                        "value": [],
                        "help": "当使用多模态大模型时，可通过此功能传入图片，结合图像内容进行问答"
                    },
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output_user",
                        "label": "将输出结果展示在会话中",
                        "type": "switch",
                        "help": "一般在问答等场景可开启，文档审核、报告生成等场景可关闭。",
                        "value": true
                    },
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "输出变量",
                        "help": "模型输出内容将会存储在该变量中。",
                        "type": "var",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "agent_xxx",
        "name": "助手",
        "description": "AI 自主进行任务规划，选择合适的知识库、数据库或工具进行调用。",
        "type": "agent",
        "v": "3",
        "tab": {
            "value": "single",
            "options": [
                {
                    "label": "单次运行",
                    "key": "single"
                },
                {
                    "label": "批量运行",
                    "key": "batch"
                }
            ]
        },
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "批处理变量",
                        "required": true,
                        "type": "user_question",
                        "test": "var",
                        "global": "self",
                        "value": [],
                        "linkage": "output",
                        "placeholder": "请选择批处理变量",
                        "tab": "batch",
                        "help": "选择需要批处理的变量，将会多次运行本节点，每次运行时从选择的变量中取一项赋值给batch_variable进行处理。"
                    }
                ]
            },
            {
                "name": "模型设置",
                "params": [
                    {
                        "key": "model_id",
                        "label": "模型",
                        "type": "agent_model",
                        "required": true,
                        "value": "",
                        "placeholder": "请在模型管理-系统模型设置中配置助手推理模型"
                    },
                    {
                        "key": "temperature",
                        "label": "温度",
                        "type": "slide",
                        "scope": [
                            0,
                            2
                        ],
                        "step": 0.1,
                        "value": 0.7
                    },
                    {
                        "key": "enable_web_search",
                        "label": "联网搜索",
                        "type": "online_switch",
                        "help": "",
                        "value": false
                    },
                ]
            },
            {
                "name": "提示词",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "系统提示词",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "placeholder": "助手画像",
                        "required": true
                    },
                    {
                        "key": "user_prompt",
                        "label": "用户提示词",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "placeholder": "用户消息内容",
                        "required": true
                    },
                    {
                        "key": "chat_history_flag",
                        "label": "历史聊天记录",
                        "type": "slide_switch",
                        "scope": [
                            0,
                            100
                        ],
                        "step": 1,
                        "value": {
                            "flag": true,
                            "value": 50
                        },
                        "help": "带入模型上下文的历史消息条数，为 0 时代表不包含上下文信息。"
                    },
                    {
                        "key": "image_prompt",
                        "label": "视觉",
                        "type": "image_prompt",
                        "value": "",
                        "help": "当使用多模态大模型时，可通过此功能传入图片，结合图像内容进行问答"
                    },
                ]
            },
            {
                "name": "知识库",
                "params": [
                    {
                        "key": "knowledge_id",
                        "label": "检索知识库范围",
                        "type": "knowledge_select_multi",
                        "placeholder": "请选择知识库",
                        "value": {
                            "type": "knowledge",
                            "value": []
                        }
                    }
                ]
            },
            {
                "name": "数据库",
                "params": [
                    {
                        "key": "sql_agent",
                        "type": "sql_config",
                        "value": {
                            "open": false,
                            "db_address": "",
                            "db_name": "",
                            "db_username": "",
                            "db_password": ""
                        }
                    }
                ]
            },
            {
                "name": "工具",
                "params": [
                    {
                        "key": "tool_list",
                        "label": "+ 添加工具",
                        "type": "add_tool",
                        "value": []
                    }
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output_user",
                        "label": "将输出结果展示在会话中",
                        "type": "switch",
                        "help": "一般在问答等场景开启，文档审核、报告生成等场景可关闭。",
                        "value": true
                    },
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "输出变量",
                        "type": "var",
                        "help": "模型输出内容将会存储在该变量中。",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "qa_retriever_xxx",
        "name": "QA知识库检索",
        "description": "从 QA 知识库中检索问题以及对应的答案。",
        "type": "qa_retriever",
        "v": "1",
        "group_params": [
            {
                "name": "检索设置",
                "params": [
                    {
                        "key": "user_question",
                        "label": "输入变量",
                        "type": "var_select",
                        "test": "var",
                        "value": "",
                        "required": true,
                        "placeholder": "请选择检索问题"
                    },
                    {
                        "key": "qa_knowledge_id",
                        "label": "QA知识库",
                        "type": "qa_select_multi",
                        "value": [],
                        "required": true,
                        "placeholder": "请选择QA知识库"
                    },
                    {
                        "key": "score",
                        "label": "相似度阈值",
                        "type": "slide",
                        "value": 0.6,
                        "scope": [
                            0.01,
                            0.99
                        ],
                        "step": 0.01,
                        "help": "低于阈值的结果将会被过滤。"
                    }
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "retrieved_result",
                        "label": "检索结果",
                        "type": "var",
                        "global": "key",
                        "value": ""
                    }
                ]
            }
        ]
    },
    {
        "id": "rag_xxx",
        "name": "文档知识库问答",
        "description": "根据用户问题从知识库中检索相关内容，结合检索结果调用大模型生成最终结果，支持多个问题并行执行。",
        "type": "rag",
        "v": "2",
        "group_params": [
            {
                "name": "知识库检索设置",
                "params": [
                    {
                        "key": "user_question",
                        "label": "用户问题",
                        "global": "self=user_prompt",
                        "type": "user_question",
                        "test": "var",
                        "help": "当选择多个问题时，将会多次运行本节点，每次运行时从批量问题中取一项进行处理。",
                        "linkage": "output_user_input",
                        "value": [],
                        "placeholder": "请选择用户问题",
                        "required": true
                    },
                    {
                        "key": "knowledge",
                        "label": "检索范围",
                        "type": "knowledge_select_multi",
                        "placeholder": "请选择知识库",
                        "value": {
                            "type": "knowledge",
                            "value": []
                        },
                        "required": true
                    },
                    {
                        "key": "user_auth",
                        "label": "用户知识库权限校验",
                        "type": "switch",
                        "value": false,
                        "help": "开启后，只会对用户有使用权限的知识库进行检索。"
                    },
                    {
                        "key": "max_chunk_size",
                        "label": "检索结果长度",
                        "type": "number",
                        "value": 15000,
                        "help": "通过此参数控制最终传给模型的知识库检索结果文本长度，超过模型支持的最大上下文长度可能会导致报错。"
                    },
                    {
                        "key": "retrieved_result",
                        "label": "检索结果",
                        "type": "var",
                        "global": "self=user_prompt"
                    }
                ]
            },
            {
                "name": "AI回复生成设置",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "系统提示词",
                        "type": "var_textarea",
                        "value": "你是一位知识库问答助手，遵守以下规则回答问题：\n1. 请用中文严谨、专业地回答用户的问题。\n2. 回答时须严格基于【参考文本】中的内容：\n\n- 如果【参考文本】中有明确与用户问题相关的文字内容，请依据相关内容进行回答；如果【参考文本】中没有任何与用户问题相关的内容，则直接回复：“没有找到相关内容”。\n- 如果相关内容中包含 markdown 格式的图片（例如 ![image](路径/IMAGE_1.png)），必须严格保留其原始 markdown 格式，不得添加引号、代码块（`或```）或其他特殊符号，也不得修改图片路径，保证可以正常渲染 markdown 图片。\n3. 当【参考文本】中的内容来源于多个不同的信息源时，若相关内容存在明显差异或冲突，请分别列出这些差异或冲突的答案；若无差异或冲突，只给出一个统一的回答即可。",
                        "required": true
                    },
                    {
                        "key": "user_prompt",
                        "label": "用户提示词",
                        "type": "var_textarea",
                        "value": "用户问题：```{{#user_question#}}```\n参考文本：```{{#retrieved_result#}}```\n你的回答：",
                        "test": "var",
                        "required": true
                    },
                    {
                        "key": "model_id",
                        "label": "模型",
                        "type": "bisheng_model",
                        "value": "",
                        "required": true,
                        "placeholder": "请在模型管理中配置 LLM 模型"
                    },
                    {
                        "key": "temperature",
                        "label": "温度",
                        "type": "slide",
                        "scope": [
                            0,
                            2
                        ],
                        "step": 0.1,
                        "value": 0.7
                    },
                    {
                        "key": "enable_web_search",
                        "label": "联网搜索",
                        "global": "self",
                        "type": "online_switch",
                        "help": "",
                        "value": false
                    },
                    {
                        "key": "show_source",
                        "label": "展示参考来源",
                        "type": "switch",
                        "value": true,
                        "help": "关闭后在会话页面不展示消息参考来源"
                    }
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output_user",
                        "label": "将输出结果展示在会话中",
                        "type": "switch",
                        "value": true,
                        "help": "一般在问答等场景开启，文档审核、报告生成等场景可关闭。"
                    },
                    {
                        "key": "output_user_input",
                        "label": "输出变量",
                        "type": "var",
                        "help": "模型输出内容将会存储在该变量中。",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "report_xxx",
        "name": "报告",
        "description": "按照预设的word模板生成报告。",
        "type": "report",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "report_info",
                        "label": "报告名称",
                        "placeholder": "请输入生成报告的名称",
                        "required": true,
                        "type": "report",
                        "value": {}
                    }
                ]
            }
        ]
    },
    {
        "id": "code_xxx",
        "name": "代码",
        "description": "自定义需要执行的代码。",
        "type": "code",
        "v": "1",
        "group_params": [
            {
                "name": "入参",
                "params": [
                    {
                        "key": "code_input",
                        "type": "code_input",
                        "test": "input",
                        "required": true,
                        "value": [
                            {
                                "key": "arg1",
                                "type": "input",
                                "label": "",
                                "value": ""
                            },
                            {
                                "key": "arg2",
                                "type": "input",
                                "label": "",
                                "value": ""
                            }
                        ]
                    }
                ]
            },
            {
                "name": "执行代码",
                "params": [
                    {
                        "key": "code",
                        "type": "code",
                        "required": true,
                        "value": "def main(arg1: str, arg2: str) -> dict: \n    return {'result1': arg1, 'result2': arg2}"
                    }
                ]
            },
            {
                "name": "出参",
                "params": [
                    {
                        "key": "code_output",
                        "type": "code_output",
                        "global": "code:value.map(el => ({ label: el.key, value: el.key }))",
                        "required": true,
                        "value": [
                            {
                                "key": "result1",
                                "type": "str"
                            },
                            {
                                "key": "result2",
                                "type": "str"
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "id": "condition_xxx",
        "name": "条件分支",
        "description": "根据条件表达式执行不同的分支。",
        "type": "condition",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "condition",
                        "label": "",
                        "type": "condition",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "end_xxx",
        "name": "结束",
        "description": "工作流运行到此结束。",
        "type": "end",
        "v": "1",
        "group_params": []
    },
]

const workflowTemplateEN = [
    {
        "id": "start_xxx",
        "name": "Start",
        "description": "The starting node of the workflow.",
        "type": "start",
        "v": "1",
        "group_params": [
            {
                "name": "Opening Guide",
                "params": [
                    {
                        "key": "guide_word",
                        "label": "Opening Words",
                        "value": "",
                        "type": "textarea",
                        "placeholder": "Send this message to the user each time the workflow starts. Supports Markdown format. Leave blank if not needed."
                    },
                    {
                        "key": "guide_question",
                        "label": "Guide Questions",
                        "value": [],
                        "type": "input_list",
                        "placeholder": "Enter guide questions",
                        "help": "Provide recommended questions to guide user input. If there are more than 3, 3 will be selected randomly."
                    }
                ]
            },
            {
                "name": "Global Variables",
                "params": [
                    {
                        "key": "current_time",
                        "global": "key",
                        "label": "Current Time",
                        "type": "var",
                        "value": ""
                    },
                    {
                        "key": "chat_history",
                        "global": "key",
                        "type": "chat_history_num",
                        "value": 10
                    },
                    {
                        "key": "preset_question",
                        "label": "Preset Question List",
                        "global": "item:input_list",
                        "type": "input_list",
                        "value": [],
                        "placeholder": "Enter batch preset questions",
                        "help": "Suitable for document review, report generation, etc. Use preset questions for batch RAG Q&A."
                    }
                ]
            }
        ]
    },
    {
        "id": "input_xxx",
        "name": "Input",
        "description": "Receive user input on the session page, supports two forms: dialog input, form input.",
        "type": "input",
        "v": "2",
        "tab": {
            "value": "dialog_input",
            "options": [
                {
                    "label": "Enter text content",
                    "key": "dialog_input",
                    "help": "Receive content entered by the user from the dialog box."
                },
                {
                    "key": "dialog_files_content",
                    "global": "key",
                    "label": "Upload file content",
                    "type": "var",
                    "tab": "dialog_input"
                },
                {
                    "key": "dialog_files_content_size",
                    "label": "Maximum length of file content (words)",
                    "type": "number",
                    "min": 0,
                    "value": 15000,
                    "tab": "dialog_input"
                },
                {
                    "key": "dialog_file_accept",
                    "label": "Upload file type",
                    "type": "select_fileaccept",
                    "value": "all",
                    "tab": "dialog_input"
                },
                {
                    "key": "dialog_image_files",
                    "global": "key",
                    "label": "Upload image files",
                    "type": "var",
                    "tab": "dialog_input",
                    "help": "Extract the image file from the uploaded file. When the assistant or large model node uses the MultiModal Machine Learning large model, this image can be passed in."
                },
                {
                    "label": "Form Input",
                    "key": "form_input",
                    "help": "Display a form on the session page to receive content submitted by the user through the form."
                }
            ]
        },
        "group_params": [
            {
                "name": "",
                "params": [
                    {
                        "key": "user_input",
                        "global": "key",
                        "label": "User Input Content",
                        "type": "var",
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_files_content",
                        "global": "key",
                        "label": "Uploaded File Content",
                        "type": "var",
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_files_content_size",
                        "label": "Retrieval Result Length (characters)",
                        "type": "number",
                        "value": 15000,
                        "tab": "dialog_input"
                    },
                    {
                        "global": "item:form_input",
                        "key": "form_input",
                        "label": "+ Add Form Item",
                        "type": "form",
                        "value": [],
                        "tab": "form_input"
                    }
                ]
            }
        ]
    },
    {
        "id": "output_xxx",
        "name": "Output",
        "description": "Send messages to users and support richer interactions, such as requesting user approval for sensitive operations or allowing users to directly modify and submit model-generated content.",
        "type": "output",
        "v": "2",
        "group_params": [
            {
                "params": [
                    {
                        "key": "message",
                        "label": "Message Content",
                        "global": "key",
                        "type": "var_textarea_file",
                        "required": true,
                        "placeholder": "Enter the message to send to the user, e.g., 'I will perform XX operation next, please confirm', or 'Here is my draft, feel free to modify it'.",
                        "value": {
                            "msg": "",
                            "files": []
                        }
                    },
                    {
                        "key": "output_result",
                        "label": "Interaction Type",
                        "global": "value.type=input",
                        "type": "output_form",
                        "required": true,
                        "value": {
                            "type": "",
                            "value": ""
                        },
                        "options": []
                    }
                ]
            }
        ]
    },
    {
        "id": "llm_xxx",
        "name": "LLM",
        "description": "Invoke a large language model to answer user questions or process tasks.",
        "type": "llm",
        "v": "2",
        "tab": {
            "value": "single",
            "options": [
                {
                    "label": "Single Run",
                    "key": "single"
                },
                {
                    "label": "Batch Run",
                    "key": "batch"
                }
            ]
        },
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "Batch Variable",
                        "global": "self",
                        "type": "user_question",
                        "value": [],
                        "required": true,
                        "linkage": "output",
                        "placeholder": "Select batch variable",
                        "help": "Select the variable to batch process. This node will run multiple times, taking one item from the selected variable each time and assigning it to batch_variable for processing.",
                        "tab": "batch"
                    }
                ]
            },
            {
                "name": "Model Settings",
                "params": [
                    {
                        "key": "model_id",
                        "label": "Model",
                        "type": "bisheng_model",
                        "value": "",
                        "required": true,
                        "placeholder": "Please configure LLM model in model management"
                    },
                    {
                        "key": "temperature",
                        "label": "Temperature",
                        "type": "slide",
                        "scope": [0, 2],
                        "step": 0.1,
                        "value": 0.7
                    }
                ]
            },
            {
                "name": "Prompts",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "System Prompt",
                        "type": "var_textarea",
                        "test": "var",
                        "value": ""
                    },
                    {
                        "key": "user_prompt",
                        "label": "User Prompt",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "required": true
                    },
                    {
                        "key": "image_prompt",
                        "label": "Visual",
                        "type": "image_prompt",
                        "value": [],
                        "help": "When using MultiModal Machine Learning large models, you can use this function to pass in images and combine them with image content for Q & A"
                    },
                ]
            },
            {
                "name": "Output",
                "params": [
                    {
                        "key": "output_user",
                        "label": "Display output in session",
                        "type": "switch",
                        "help": "Typically enabled in Q&A scenarios and disabled in document review or report generation scenarios.",
                        "value": true
                    },
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "Output Variable",
                        "type": "var",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "agent_xxx",
        "name": "Agent",
        "description": "AI autonomously plans tasks and selects appropriate knowledge bases or tools for invocation.",
        "type": "agent",
        "v": "2",
        "tab": {
            "value": "single",
            "options": [
                {
                    "label": "Single Run",
                    "key": "single"
                },
                {
                    "label": "Batch Run",
                    "key": "batch"
                }
            ]
        },
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "Batch Variable",
                        "required": true,
                        "type": "user_question",
                        "global": "self",
                        "value": [],
                        "linkage": "output",
                        "placeholder": "Select batch variable",
                        "tab": "batch",
                        "help": "Select the variable to batch process. This node will run multiple times, taking one item from the selected variable each time and assigning it to batch_variable for processing."
                    }
                ]
            },
            {
                "name": "Model Settings",
                "params": [
                    {
                        "key": "model_id",
                        "label": "Model",
                        "type": "agent_model",
                        "required": true,
                        "value": "",
                        "placeholder": "Please configure the assistant inference model in Model Management - System Model Settings"
                    },
                    {
                        "key": "temperature",
                        "label": "Temperature",
                        "type": "slide",
                        "scope": [0, 2],
                        "step": 0.1,
                        "value": 0.7
                    }
                ]
            },
            {
                "name": "Prompts",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "System Prompt",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "placeholder": "Assistant Persona",
                        "required": true
                    },
                    {
                        "key": "user_prompt",
                        "label": "User Prompt",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "placeholder": "User Message",
                        "required": true
                    },
                    {
                        "key": "chat_history_flag",
                        "label": "Historical Chat Records",
                        "type": "slide_switch",
                        "scope": [0, 100],
                        "step": 1,
                        "value": {
                            "flag": true,
                            "value": 50
                        },
                        "help": "Include historical chat records."
                    },
                    {
                        "key": "image_prompt",
                        "label": "Visual",
                        "type": "image_prompt",
                        "value": "",
                        "help": "When using MultiModal Machine Learning large models, you can use this function to pass in images and combine them with image content for Q & A"
                    },
                ]
            },
            {
                "name": "Knowledge Base",
                "params": [
                    {
                        "key": "knowledge_id",
                        "label": "Knowledge Base Scope",
                        "type": "knowledge_select_multi",
                        "placeholder": "Select Knowledge Base",
                        "value": {
                            "type": "knowledge",
                            "value": []
                        }
                    }
                ]
            },
            {
                "name": "Database",
                "params": [
                    {
                        "key": "sql_agent",
                        "type": "sql_config",
                        "value": {
                            "open": false,
                            "db_address": "",
                            "db_name": "",
                            "db_username": "",
                            "db_password": ""
                        }
                    }
                ]
            },
            {
                "name": "Tools",
                "params": [
                    {
                        "key": "tool_list",
                        "label": "+ Add Tool",
                        "type": "add_tool",
                        "value": []
                    }
                ]
            },
            {
                "name": "Output",
                "params": [
                    {
                        "key": "output_user",
                        "label": "Display output in session",
                        "type": "switch",
                        "help": "Typically enabled in Q&A scenarios and disabled in document review or report generation scenarios.",
                        "value": true
                    },
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "Output Variable",
                        "type": "var",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "qa_retriever_xxx",
        "name": "QA Retrieval",
        "description": "Retrieve questions and corresponding answers from the QA knowledge base.",
        "type": "qa_retriever",
        "v": "1",
        "group_params": [
            {
                "name": "Retrieval Settings",
                "params": [
                    {
                        "key": "user_question",
                        "label": "Input Variable",
                        "type": "var_select",
                        "test": "var",
                        "value": "",
                        "required": true,
                        "placeholder": "Select retrieval question"
                    },
                    {
                        "key": "qa_knowledge_id",
                        "label": "QA Knowledge Base",
                        "type": "qa_select_multi",
                        "value": [],
                        "required": true,
                        "placeholder": "Select QA knowledge base"
                    },
                    {
                        "key": "score",
                        "label": "Similarity Threshold",
                        "type": "slide",
                        "value": 0.6,
                        "scope": [
                            0.01,
                            0.99
                        ],
                        "step": 0.01,
                        "help": "Results below this threshold will be filtered out."
                    }
                ]
            },
            {
                "name": "Output",
                "params": [
                    {
                        "key": "retrieved_result",
                        "label": "Retrieval Result",
                        "type": "var",
                        "global": "key",
                        "value": ""
                    }
                ]
            }
        ]
    },
    {
        "id": "rag_xxx",
        "name": "Document Retrieval",
        "description": "Retrieve relevant content from the knowledge base based on user questions and generate final answers using the retrieved results and a large language model. Supports parallel execution for multiple questions.",
        "type": "rag",
        "v": "1",
        "group_params": [
            {
                "name": "Knowledge Base Retrieval Settings",
                "params": [
                    {
                        "key": "user_question",
                        "label": "User Question",
                        "global": "self=user_prompt",
                        "type": "user_question",
                        "test": "var",
                        "help": "If multiple questions are selected, this node will run multiple times, taking one question at a time for processing.",
                        "linkage": "output_user_input",
                        "value": [],
                        "placeholder": "Select user question",
                        "required": true
                    },
                    {
                        "key": "knowledge",
                        "label": "Retrieval Scope",
                        "type": "knowledge_select_multi",
                        "placeholder": "Select knowledge base",
                        "value": {
                            "type": "knowledge",
                            "value": []
                        },
                        "required": true
                    },
                    {
                        "key": "user_auth",
                        "label": "User Knowledge Base Permission Validation",
                        "type": "switch",
                        "value": false,
                        "help": "When enabled, retrieval will only be performed on knowledge bases the user has permission to access."
                    },
                    {
                        "key": "max_chunk_size",
                        "label": "Retrieval Result Length",
                        "type": "number",
                        "value": 15000,
                        "help": "Controls the length of the retrieved text passed to the model. Exceeding the maximum context length supported by the model may cause errors."
                    },
                    {
                        "key": "retrieved_result",
                        "label": "Retrieval Result",
                        "type": "var",
                        "global": "self=user_prompt"
                    }
                ]
            },
            {
                "name": "AI Response Generation Settings",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "System Prompt",
                        "type": "var_textarea",
                        "value": "You are a knowledge base Q&A assistant: \n1. Answer user questions in Chinese with professional and rigorous responses.\n2. Use the provided [Reference Text] for answers. Only answer if the text clearly relates to the user question, and do not use your own knowledge.\n3. If [Reference Text] contains conflicting or differing answers, list all the answers. If there is no conflict, provide a single final result.\n4. If the [Reference Text] is not relevant, reply with 'No relevant content found.'",
                        "required": true
                    },
                    {
                        "key": "user_prompt",
                        "label": "User Prompt",
                        "type": "var_textarea",
                        "value": "User Question: {{#user_question#}}\nReference Text: {{#retrieved_result#}}\nYour Answer:",
                        "test": "var",
                        "required": true
                    },
                    {
                        "key": "model_id",
                        "label": "Model",
                        "type": "bisheng_model",
                        "value": "",
                        "required": true,
                        "placeholder": "Please configure LLM model in model management"
                    },
                    {
                        "key": "temperature",
                        "label": "Temperature",
                        "type": "slide",
                        "scope": [0, 2],
                        "step": 0.1,
                        "value": 0.7
                    }
                ]
            },
            {
                "name": "Output",
                "params": [
                    {
                        "key": "output_user",
                        "label": "Display output in session",
                        "type": "switch",
                        "value": true,
                        "help": "Typically enabled in Q&A scenarios and disabled in document review or report generation scenarios."
                    },
                    {
                        "key": "output_user_input",
                        "label": "Output Variable",
                        "type": "var",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "report_xxx",
        "name": "Report",
        "description": "Generate reports based on pre-defined Word templates.",
        "type": "report",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "report_info",
                        "label": "Report Name",
                        "placeholder": "Enter the name of the report to generate",
                        "required": true,
                        "type": "report",
                        "value": {}
                    }
                ]
            }
        ]
    },
    {
        "id": "condition_xxx",
        "name": "Condition",
        "description": "Execute different branches based on conditional expressions.",
        "type": "condition",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "condition",
                        "label": "",
                        "type": "condition",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "code_xxx",
        "name": "Code",
        "description": "Customize and execute specific code.",
        "type": "code",
        "v": "1",
        "group_params": [
            {
                "name": "Input Parameters",
                "params": [
                    {
                        "key": "code_input",
                        "type": "code_input",
                        "test": "input",
                        "required": true,
                        "value": [
                            {
                                "key": "arg1",
                                "type": "input",
                                "label": "",
                                "value": ""
                            },
                            {
                                "key": "arg2",
                                "type": "input",
                                "label": "",
                                "value": ""
                            }
                        ]
                    }
                ]
            },
            {
                "name": "Execute Code",
                "params": [
                    {
                        "key": "code",
                        "type": "code",
                        "required": true,
                        "value": "def main(arg1: str, arg2: str) -> dict: \n    return {'result1': arg1, 'result2': arg2}"
                    }
                ]
            },
            {
                "name": "Output Parameters",
                "params": [
                    {
                        "key": "code_output",
                        "type": "code_output",
                        "global": "code:value.map(el => ({ label: el.key, value: el.key }))",
                        "required": true,
                        "value": [
                            {
                                "key": "result1",
                                "type": "str"
                            },
                            {
                                "key": "result2",
                                "type": "str"
                            }
                        ]
                    }
                ]
            }
        ]
    },
    {
        "id": "end_xxx",
        "name": "End",
        "description": "The workflow ends here.",
        "type": "end",
        "group_params": []
    }
];
