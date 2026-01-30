import { WorkFlow } from "@/types/flow";
import axios from "../request";

/**
 * 获取工作流节点模板s
 */
export const getWorkflowNodeTemplate = async (): Promise<any[]> => {
    return new Promise(res => setTimeout(() => {
        res(workflowTemplate)
    }, 100));
}

/**
 * 获取某工作流报告模板信息
 */
export const getWorkflowReportTemplate = async (key: string, flowId: string): Promise<any> => {
    return await axios.get(`/api/v1/workflow/report/file?version_key=${key}&workflow_id=${flowId}`);
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
        data.logo = data.logo.replace(/^\/\w+/, '')
    }
    return await axios.put(`/api/v1/workflow/versions/${versionId}`, data);
}



/**
 * 删除版本.
 *
 * @param {string} versionId - 要删除的版本ID.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function deleteVersion(versionId: string) {
    return await axios.delete(`/api/v1/workflow/versions/${versionId}`);
}

/**
 * 创建新的工作流版本.
 *
 * @param {object} versionData - 新版本的数据.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function createWorkFlowVersion(flow_id, versionData: { name: string, description: string, original_version_id: number, data: any }) {
    return await axios.post(`/api/v1/workflow/versions?flow_id=${flow_id}`, versionData);
}

/**
 * 获取单个版本的信息.
 *
 * @param {string} versionId - 版本的ID.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function getVersionDetails(versionId: string) {
    return await axios.get(`/api/v1/workflow/versions/${versionId}`);
}

/**
 * 更新版本信息.
 *
 * @param {string} versionId - 要更新的版本ID.
 * @param {object} versionData - 更新的版本数据.
 * @returns {Promise<any>}.
 * @throws .
 */
export async function updateVersion(versionId: string, versionData: { name: string, description: string, data: any }) {
    return await axios.put(`/api/v1/workflow/versions/${versionId}`, versionData);
}

/**
 * 获取工作流对应的版本列表.
 *
 * @returns {Promise<any>}.
 * @throws .
 */
export async function getWorkFlowVersions(flow_id): Promise<{ data: any[], total: number }> {
    return await axios.get(`/api/v1/workflow/versions`, {
        params: { flow_id }
    });
}


/** 上线工作流 & 修改信息 
 * status: 2 上线 1 下线
*/
export const onlineWorkflow = async (flow, status = ''): Promise<any> => {
    const { name, description, logo } = flow
    const data = { name, description, logo }
    if (status) {
        data['status'] = status
        delete data['logo']
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
export const runWorkflowNodeApi = async ({ node_input, data, workflow_id }): Promise<any> => {
    return await axios.post(`/api/v1/workflow/run_once`, {
        node_input,
        workflow_id,
        node_data: {
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
        "name": "true",
        "description": "true",
        "type": "start",
        "v": "3",
        "group_params": [
            {
                "name": "开场引导",
                "params": [
                    {
                        "key": "guide_word",
                        "label": "true",
                        "value": "",
                        "type": "textarea",
                        "placeholder": "true"
                    },
                    {
                        "key": "guide_question",
                        "label": "true",
                        "value": [],
                        "type": "input_list",
                        "placeholder": "true",
                        "help": "true"
                    }
                ]
            },
            {
                "name": "全局变量",
                "params": [
                    {
                        "key": "user_info",
                        "global": "key",
                        "label": "true",
                        "type": "var",
                        "value": "",
                    },
                    {
                        "key": "current_time",
                        "global": "key",
                        "label": "true",
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
                        "label": "true",
                        "global": "item:input_list",
                        "type": "input_list",
                        "value": [],
                        "placeholder": "true",
                        "help": "true"
                    },
                    {
                        "key": "custom_variables",
                        "label": "true",
                        "global": "item:input_list",
                        "type": "global_var",
                        "value": [],
                        "help": "true"
                    }
                ]
            }
        ]
    },
    {
        "id": "input_xxx",
        "name": "true",
        "description": "true",
        "type": "input",
        "v": "3",
        "tab": {
            "value": "dialog_input",
            "options": [
                {
                    "label": "true",
                    "key": "dialog_input",
                    "help": "true"
                },
                {
                    "label": "true",
                    "key": "form_input",
                    "help": "true"
                }
            ]
        },
        "group_params": [
            {
                "name": "接收文本",
                "params": [
                    {
                        "key": "user_input",
                        "global": "key",
                        "label": "true",
                        "type": "var",
                        "tab": "dialog_input"
                    }
                ]
            },
            {
                "name": "",
                "groupKey": "inputfile",
                "params": [
                    {
                        "groupTitle": true,
                        "key": "user_inputfile",
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
                        "key": "dialog_files_content",
                        "global": "item:group_input_file",
                        "label": "true",
                        "type": "var",
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_files_content_size",
                        "label": "true",
                        "type": "char_number",
                        "min": 0,
                        "value": 15000,
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_file_accept",
                        "label": "true",
                        "type": "select_fileaccept",
                        "value": "all",
                        "tab": "dialog_input"
                    },
                    {
                        "key": "dialog_image_files",
                        "global": "item:group_input_file",
                        "label": "true",
                        "type": "var",
                        "tab": "dialog_input",
                        "help": "true"
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
                        "placeholder": "true",
                        "required": true
                    },
                    {
                        "key": "recommended_history_num",
                        "label": "true",
                        "type": "slide",
                        "tab": "dialog_input",
                        "help": "true",
                        "scope": [
                            1,
                            10
                        ],
                        "step": 1,
                        "value": 2
                    }
                ]
            },
            {
                "name": "",
                "params": [
                    {
                        "key": "form_input",
                        "global": "item:form_input",
                        "label": "true",
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
        "name": "true",
        "description": "true",
        "type": "output",
        "v": "2",
        "group_params": [
            {
                "params": [
                    {
                        "key": "message",
                        "label": "true",
                        "global": "key",
                        "type": "var_textarea_file",
                        "required": true,
                        "placeholder": "true",
                        "value": {
                            "msg": "",
                            "files": []
                        }
                    },
                    {
                        "key": "output_result",
                        "label": "true",
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
        "name": "true",
        "description": "true",
        "type": "llm",
        "v": "2",
        "tab": {
            "value": "single",
            "options": [
                {
                    "label": "true",
                    "key": "single"
                },
                {
                    "label": "true",
                    "key": "batch"
                }
            ]
        },
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "true",
                        "global": "self",
                        "type": "user_question",
                        "test": "var",
                        "value": [],
                        "required": true,
                        "linkage": "output",
                        "placeholder": "true",
                        "help": "true",
                        "tab": "batch"
                    }
                ]
            },
            {
                "name": "模型设置",
                "params": [
                    {
                        "key": "model_id",
                        "label": "true",
                        "type": "bisheng_model",
                        "value": "",
                        "required": true,
                        "placeholder": "true"
                    },
                    {
                        "key": "temperature",
                        "label": "true",
                        "type": "slide",
                        "scope": [
                            0,
                            2
                        ],
                        "step": 0.1,
                        "value": 0.7
                    }
                ]
            },
            {
                "name": "提示词",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "true",
                        "type": "var_textarea",
                        "test": "var",
                        "value": ""
                    },
                    {
                        "key": "user_prompt",
                        "label": "true",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "required": true
                    },
                    {
                        "key": "image_prompt",
                        "label": "true",
                        "type": "image_prompt",
                        "value": [],
                        "help": "true"
                    },
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output_user",
                        "label": "true",
                        "type": "switch",
                        "help": "true",
                        "value": true
                    },
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "true",
                        "help": "true",
                        "type": "var",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "agent_xxx",
        "name": "true",
        "description": "true",
        "type": "agent",
        "v": "2",
        "tab": {
            "value": "single",
            "options": [
                {
                    "label": "true",
                    "key": "single"
                },
                {
                    "label": "true",
                    "key": "batch"
                }
            ]
        },
        "group_params": [
            {
                "params": [
                    {
                        "key": "batch_variable",
                        "label": "true",
                        "required": true,
                        "type": "user_question",
                        "test": "var",
                        "global": "self",
                        "value": [],
                        "linkage": "output",
                        "placeholder": "true",
                        "tab": "batch",
                        "help": "true"
                    }
                ]
            },
            {
                "name": "模型设置",
                "params": [
                    {
                        "key": "model_id",
                        "label": "true",
                        "type": "agent_model",
                        "required": true,
                        "value": "",
                        "placeholder": "true"
                    },
                    {
                        "key": "temperature",
                        "label": "true",
                        "type": "slide",
                        "scope": [
                            0,
                            2
                        ],
                        "step": 0.1,
                        "value": 0.7
                    }
                ]
            },
            {
                "name": "提示词",
                "params": [
                    {
                        "key": "system_prompt",
                        "label": "true",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "true",
                        "placeholder": "true",
                        "required": true
                    },
                    {
                        "key": "user_prompt",
                        "label": "true",
                        "type": "var_textarea",
                        "test": "var",
                        "value": "",
                        "placeholder": "true",
                        "required": true
                    },
                    {
                        "key": "chat_history_flag",
                        "label": "true",
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
                        "help": "true"
                    },
                    {
                        "key": "image_prompt",
                        "label": "true",
                        "type": "image_prompt",
                        "value": "",
                        "help": "true"
                    },
                ]
            },
            {
                "name": "知识库",
                "params": [
                    {
                        "key": "knowledge_id",
                        "label": "true",
                        "type": "knowledge_select_multi",
                        "placeholder": "true",
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
                        "label": "true",
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
                        "label": "true",
                        "type": "switch",
                        "help": "true",
                        "value": true
                    },
                    {
                        "key": "output",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "label": "true",
                        "type": "var",
                        "help": "true",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "qa_retriever_xxx",
        "name": "true",
        "description": "true",
        "type": "qa_retriever",
        "v": "1",
        "group_params": [
            {
                "name": "检索设置",
                "params": [
                    {
                        "key": "user_question",
                        "label": "true",
                        "type": "var_select",
                        "test": "var",
                        "value": "",
                        "required": true,
                        "placeholder": "true"
                    },
                    {
                        "key": "qa_knowledge_id",
                        "label": "true",
                        "type": "qa_select_multi",
                        "value": [],
                        "required": true,
                        "placeholder": "true"
                    },
                    {
                        "key": "score",
                        "label": "true",
                        "type": "slide",
                        "value": 0.8,
                        "scope": [
                            0.01,
                            0.99
                        ],
                        "step": 0.01,
                        "help": "true"
                    }
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "retrieved_result",
                        "label": "true",
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
        "name": "true",
        "description": "true",
        "type": "rag",
        "v": "2",
        "group_params": [
            {
                "name": "知识库检索设置",
                "params": [
                    {
                        "key": "user_question",
                        "label": "true",
                        "global": "self=user_prompt",
                        "type": "user_question",
                        "test": "var",
                        "help": "true",
                        "linkage": "output_user_input",
                        "value": [],
                        "placeholder": "true",
                        "required": true
                    },
                    {
                        "key": "knowledge",
                        "label": "true",
                        "type": "knowledge_select_multi",
                        "placeholder": "true",
                        "value": {
                            "type": "knowledge",
                            "value": []
                        },
                        "required": true
                    },
                    {
                        "key": "metadata_filter",
                        "label": "true",
                        "type": "metadata_filter",
                        "value": {},
                    },
                    {
                        "key": "advanced_retrieval_switch",
                        "label": "true",
                        "type": "search_switch",
                        "value": {},
                    },
                    {
                        "key": "retrieved_result",
                        "label": "true",
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
                        "label": "true",
                        "type": "var_textarea",
                        "value": "true",
                        "required": true
                    },
                    {
                        "key": "user_prompt",
                        "label": "true",
                        "type": "var_textarea",
                        "value": "true",
                        "test": "var",
                        "required": true
                    },
                    {
                        "key": "model_id",
                        "label": "true",
                        "type": "bisheng_model",
                        "value": "",
                        "required": true,
                        "placeholder": "true"
                    },
                    {
                        "key": "temperature",
                        "label": "true",
                        "type": "slide",
                        "scope": [
                            0,
                            2
                        ],
                        "step": 0.1,
                        "value": 0.7
                    }
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "output_user",
                        "label": "true",
                        "type": "switch",
                        "value": true,
                        "help": "true"
                    },
                    {
                        "key": "output_user_input",
                        "label": "true",
                        "type": "var",
                        "help": "true",
                        "global": "code:value.map(el => ({ label: el.label, value: el.key }))",
                        "value": []
                    }
                ]
            }
        ]
    },
    {
        "id": "knowledge_retriever_xxx",
        "name": "true",
        "description": "true",
        "type": "knowledge_retriever",
        "v": "1",
        "group_params": [
            {
                "name": "知识库检索设置",
                "params": [
                    {
                        "key": "user_question",
                        "label": "true",
                        "global": "self=user_prompt",
                        "type": "user_question",
                        "test": "var",
                        "help": "true",
                        "linkage": "retrieved_result",
                        "value": [],
                        "placeholder": "true",
                        "required": true
                    },
                    {
                        "key": "knowledge",
                        "label": "true",
                        "type": "knowledge_select_multi",
                        "placeholder": "true",
                        "value": {
                            "type": "knowledge",
                            "value": []
                        },
                        "required": true
                    },
                    {
                        "key": "metadata_filter",
                        "label": "true",
                        "type": "metadata_filter",
                        "value": {},
                    },
                    {
                        "key": "advanced_retrieval_switch",
                        "label": "true",
                        "type": "search_switch",
                        "value": {},
                    },
                ]
            },
            {
                "name": "输出",
                "params": [
                    {
                        "key": "retrieved_result",
                        "label": "true",
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
        "name": "true",
        "description": "true",
        "type": "report",
        "v": "1",
        "group_params": [
            {
                "params": [
                    {
                        "key": "report_info",
                        "label": "true",
                        "placeholder": "true",
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
        "name": "true",
        "description": "true",
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
        "name": "true",
        "description": "true",
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
        "name": "true",
        "description": "true",
        "type": "end",
        "v": "1",
        "group_params": []
    },
]
