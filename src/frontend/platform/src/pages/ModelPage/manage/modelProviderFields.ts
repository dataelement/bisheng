import type { ConfigField } from './speechConfig';

export function getModelProviders(): Record<string, ConfigField[]> {
    return {
    ollama: [
        {
            label: "Base URL",
            type: "text",
            example: "http://ip:11434",
            default: "",
            required: true,
            key: "base_url",
        },
    ],
    xinference: [
        {
            label: "Base URL",
            type: "text",
            example: "http://ip:9997/v1",
            default: "",
            required: true,
            key: "openai_api_base",
        }
    ],
    llamacpp: [
        {
            label: "Base URL",
            type: "text",
            example: "http://ip:8080/v1",
            default: "",
            required: true,
            key: "openai_api_base",
        },
    ],
    vllm: [
        {
            label: "Base URL",
            type: "text",
            example: "http://ip:8000/v1",
            default: "",
            required: true,
            key: "openai_api_base",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: false,
            key: "openai_api_key",
        },
    ],
    openai: [
        {
            label: "OpenAI API Base",
            type: "text",
            placeholder: "",
            default: "https://api.openai.com/v1",
            required: false,
            key: "openai_api_base",
        },
        {
            label: "OpenAI Proxy",
            type: "text",
            placeholder: "http://host:port",
            default: "",
            required: false,
            key: "openai_proxy",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "openai_api_key",
        },
    ],
    azure_openai: [
        {
            label: "Azure Endpoint",
            type: "text",
            example: "https://xxx.openai.azure.com/",
            default: "",
            required: true,
            key: "azure_endpoint",
        },
        {
            label: "Azure OpenAI API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "openai_api_key",
        },
        {
            label: "OpenAI API Version",
            type: "text",
            example: "2024-02-01",
            default: "",
            required: true,
            key: "openai_api_version",
        },
    ],
    qwen: [
        {
            label: "Base URL",
            type: "text",
            placeholder: "",
            default: "https://dashscope.aliyuncs.com/compatible-mode/v1",
            required: true,
            key: "openai_api_base",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "openai_api_key",
        },
    ],
    qianfan: [
        {
            label: "Base URL",
            type: "",
            placeholder: "",
            default: "https://qianfan.baidubce.com/v2",
            required: true,
            key: "base_url",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_key",
        },
    ],
    zhipu: [
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "openai_api_key",
        },
        {
            label: "Base URL",
            type: "text",
            placeholder: "",
            default: "https://open.bigmodel.cn/api/paas/v4/",
            required: true,
            key: "openai_api_base",
        },
    ],
    deepseek: [
        {
            label: "Base URL",
            type: "text",
            placeholder: "",
            default: "https://api.deepseek.com",
            required: true,
            key: "openai_api_base",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "openai_api_key",
        },
    ],
    MindIE: [
        {
            label: "Base URL",
            type: "text",
            example: "http://ip:port/v1",
            default: "",
            required: true,
            key: "base_url",
        },
    ],
    spark: [
        // {
        //     label: "App ID",
        //     type: "text",
        //     placeholder: "",
        //     default: "",
        //     required: true,
        //     key: "appid",
        // },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_key",
        },
        {
            label: "API Secret",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_secret",
        },
        {
            label: "Base URL",
            type: "text",
            placeholder: "",
            default: "https://spark-api-open.xf-yun.com/v1",
            required: true,
            key: "openai_api_base",
        }
    ],
    minimax: [
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "openai_api_key",
        },
        // {
        //     label: "Group ID",
        //     type: "text",
        //     placeholder: "",
        //     default: "",
        //     required: true,
        //     key: "minimax_group_id",
        // },
        {
            label: "API Host",
            type: "text",
            placeholder: "",
            default: "https://api.minimax.cn/v1",
            required: true,
            key: "openai_api_base",
        },
    ],
    anthropic: [
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "anthropic_api_key",
        },
        {
            label: "API URL",
            type: "text",
            placeholder: "",
            default: "",
            required: true,
            key: "anthropic_api_url",
        },
    ],
    bisheng_rt: [
        {
            label: "API Host",
            type: "text",
            placeholder: "",
            default: "",
            required: true,
            key: "host_base_url",
        }
    ],
    tencent: [
        {
            label: "Base URL",
            type: "text",
            default: "https://api.hunyuan.cloud.tencent.com/v1",
            required: true,
            key: "base_url",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_key",
        },
    ],
    moonshot: [
        {
            label: "Base URL",
            type: "text",
            example: "https://api.moonshot.cn/v1",
            default: "https://api.moonshot.cn/v1",
            required: true,
            key: "base_url",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_key",
        },
    ],
    volcengine: [
        {
            label: "Base URL",
            type: "text",
            example: "https://ark.cn-beijing.volces.com/api/v3",
            default: "https://ark.cn-beijing.volces.com/api/v3",
            required: true,
            key: "base_url",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_key",
        },
    ],
    "silicon": [
        {
            label: "Base URL",
            type: "text",
            placeholder: "",
            default: "https://api.siliconflow.cn/v1",
            required: true,
            key: "openai_api_base",
        },
        {
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "api_key",
        },
    ]
};
}

/** Providers the backend can serve rerank models for (backend: bisheng/llm/domain/llm/rerank.py). */
export const rerankProviders = ['openai', 'xinference', 'llamacpp', 'vllm', 'qwen', 'qianfan', 'silicon'];
