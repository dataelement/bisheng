import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";

const modelProviders = {
    ollama: [
        {
            label: "Base URL",
            type: "text",
            placeholder: "格式示例：http://ip:11434",
            default: "",
            required: true,
            key: "base_url",
        },
    ],
    xinference: [
        {
            label: "Base URL",
            type: "text",
            placeholder: "格式示例：http://ip:9997/v1",
            default: "",
            required: true,
            key: "openai_api_base",
        }
    ],
    llamacpp: [
        {
            label: "Base URL",
            type: "text",
            placeholder: "格式示例：http://ip:8080/v1",
            default: "",
            required: true,
            key: "openai_api_base",
        },
    ],
    vllm: [
        {
            label: "Base URL",
            type: "text",
            placeholder: "格式示例：http://ip:8000/v1",
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
            placeholder: "",
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
            placeholder: "格式示例：https://xxx.openai.azure.com/",
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
            placeholder: "格式示例：2024-02-01",
            default: "",
            required: true,
            key: "openai_api_version",
        },
    ],
    qwen: [
        {
            label: "Base URL",
            type: "text",
            default: "https://dashscope.aliyuncs.com/compatible-mode/v1",
            placeholder: "",
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
            label: "API Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "wenxin_api_key",
        },
        {
            label: "Secret Key",
            type: "password",
            placeholder: "",
            default: "",
            required: true,
            key: "wenxin_secret_key",
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
            label: "Base Url",
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
    spark: [
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
            label: "Base Url",
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
            label: "Api Host",
            type: "text",
            placeholder: "",
            default: "https://api.minimax.chat/v1",
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
            label: "Api Host",
            type: "text",
            placeholder: "",
            default: "",
            required: true,
            key: "host_base_url",
        }
    ]
};


const FormField = ({ showDefault, field, value, onChange }) => {
    useEffect(() => {
        showDefault && field.default && onChange(field.key, field.default)
    }, [showDefault])

    return (
        <div className="mb-2">
            <Label className="bisheng-label">{field.label}</Label>
            <Input
                type={field.type}
                placeholder={field.placeholder}
                value={value}
                onChange={(e) => onChange(field.key, e.target.value)}
                required={field.required}
            />
        </div>
    );
};


const CustomForm = forwardRef(({ showDefault, provider, formData }, ref) => {
    const [form, setForm] = useState(formData);
    const fields = modelProviders[provider] || [];
    console.log('form :>> ', form);

    const handleChange = (key, value) => {
        setForm((prevData) => ({
            ...prevData,
            [key]: value,
        }));
    };

    useImperativeHandle(ref, () => ({
        getData() {
            const errorObj = fields.find(field => field.required && !form[field.key]);
            return [form, errorObj ? errorObj.label : ''];
        }
    }))

    return (
        <div className="overflow-hidden">
            {fields.map((field) => (
                <FormField
                    key={field.key}
                    showDefault={showDefault}
                    field={field}
                    value={form[field.key] || ''}
                    onChange={handleChange}
                />
            ))}
        </div>
    );
});

export default CustomForm;
