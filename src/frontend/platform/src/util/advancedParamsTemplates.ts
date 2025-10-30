// src/configs/advancedParamsTemplates.ts

// 定义高级参数配置的类型接口
export interface AdvancedParams {
    cache?: any;
    extra_body?: any;
    request_timeout?: any;
    seed?: any;
    streaming?: boolean;
    temperature?: number | null;
    top_p?: number | null;
    reasoning?: any;
    top_p?: number;
    max_retries?: number;
    disable_streaming?: boolean;
    model_kwargs?: any;
    model?: any;
    endpoint?: any;
    tags?: any;
    default_request_timeout?: any;
    api_base?: any;
    default_headers?: any;
    service_tier?: any;
    base_url?: string;
    http_client?: any;
    max_tokens?: number;
    n?: number;
    tiktoken_model_name?: any;
    num_ctx?: number;
    num_gpu?: any;
    chunk_size?: number;
    [key: string]: any; // 允许其他自定义参数
  }
  
  // LLM模型模板
  export const llmTemplates: Record<string, AdvancedParams> = {
    // 基础模板
    'ollama-llm': {
      "temperature": 0.8,
      "top_p": 0.9,
      "seed": null,
      "reasoning": null
    },
  
    'openai-llm': {
      "cache": null,
      "extra_body": null,
      "request_timeout": null,
      "seed": null,
      "streaming": false,
      "temperature": 0.7,
      "top_p": 1
    },
  
    'volcengine-llm': {
      "cache": null,
      "extra_body": {
        "thinking": {"type": "enabled"}
      },
      "request_timeout": null,
      "seed": null,
      "streaming": false,
      "temperature": 0.7,
      "top_p": 1
    },
  
    'silicon-llm': {
      "cache": null,
      "extra_body": {
        "enable_thinking": true
      },
      "request_timeout": null,
      "seed": null,
      "streaming": false,
      "temperature": 0.7,
      "top_p": 1
    },

    'mindie-llm': {
      "cache": null,
      "extra_body": {
        "chat_template_kwargs": {"enable_thinking": true}
      },
      "request_timeout": null,
      "seed": null,
      "streaming": false,
      "temperature": 0.7,
      "top_p": 1
    },
  
    'qwen-llm': {
      "top_p": 0.8,
      "streaming": false,
      "max_retries": 10,
      "cache": null,
      "disable_streaming": false,
      "model_kwargs": {
        "enable_thinking": true
      }
    },
  
    'qianfan-llm':{
      "cache": null,
      "extra_body": null,
      "request_timeout": null,
      "seed": null,
      "streaming": false,
      "temperature": 0.7,
      "top_p": 1
  },
  
    'zhipu-llm': {
      "temperature": 0.95,
      "top_p": 0.7,
      "cache": null,
      "disable_streaming": false,
      "streaming": false,
      "tags": null
    },
  
    'minimax-llm': {
      "cache": null,
      "disable_streaming": false,
      "temperature": 0.7,
      "top_p": 0.95,
      "streaming": false
    },
  
    'anthropic-llm': {
      "cache": null,
      "default_request_timeout": null,
      "disable_streaming": false,
      "streaming": false,
      "temperature": null,
      "top_p": null,
      "model_kwargs": null
    },
  
    'deepseek-llm':{
      "cache": null,
      "default_headers": null,
      "disable_streaming": false,
      "extra_body": null,
      "request_timeout": null,
      "seed": null,
      "service_tier": null,
      "streaming": false,
      "temperature": null,
      "top_p": null,
  },
  
  
    'moonshot-llm': {
      "cache": null,
      "disable_streaming": false,
      "http_client": null,
      "max_retries": 2,
      "max_tokens": 1024,
      "n": 1,
      "streaming": false,
      "tags": null,
      "temperature": 0.3,
      "tiktoken_model_name": null
  }
    
  };
  
  // Embedding模型模板
  export const embeddingTemplates: Record<string, AdvancedParams> = {
    'ollama-embedding': {
      "num_ctx": 2048,
      "num_gpu": null
    },
  
    'xinference-embedding': {
      "chunk_size": 1000
    },
  
    'llamacpp-embedding': {
      "chunk_size": 1000
    },
  
    'vllm-embedding': {
      "chunk_size": 1000
    },
  
    'openai-embedding': {
      "chunk_size": 1000
    },
  
    'zhipu-embedding': {
      "chunk_size": 1000
    },
  
    'minimax-embedding': {
      "chunk_size": 1000
    },
  
    'tencent-embedding': {
      "chunk_size": 1000
    },
  
    'volcengine-embedding': {
      "chunk_size": 1000
    },
  
    'silicon-embedding': {
      "chunk_size": 1000
    },
  
    'azure-embedding': {
      "chunk_size": 2048
    },
  
    'qwen-embedding': {
      "max_retries": 5
    },
  
    'qianfan-embedding': {
      "chunk_size": 16
    }
  };
  
  // 模型类型到模板的映射 (LLM)
  export const llmModelTypeToTemplateKey: Record<string, string> = {
    // OpenAI 风格模型
    'openai': 'openai-llm',
    'azure_openai': 'openai-llm',
    'xinference': 'openai-llm',
    'llamacpp': 'openai-llm',
    'vllm': 'openai-llm',
    'spark': 'openai-llm',    // 讯飞星火
    'tencent': 'openai-llm',  // 腾讯云
    
    // 其他特殊模型
    'ollama': 'ollama-llm',
    'volcengine': 'volcengine-llm',
    'silicon': 'silicon-llm',
    'MindIE': 'mindie-llm',
    'qwen': 'qwen-llm',       // 通义千问
    'qianfan': 'qianfan-llm', // 百度千帆
    'zhipu': 'zhipu-llm',     // 智谱清言
    'minimax': 'minimax-llm',
    'anthropic': 'anthropic-llm',
    'deepseek': 'deepseek-llm',
    'moonshot': 'moonshot-llm' // 月之暗面
  };
  
  // 模型类型到模板的映射 (Embedding)
  export const embeddingModelTypeToTemplateKey: Record<string, string> = {
    'ollama': 'ollama-embedding',
    'xinference': 'xinference-embedding',
    'llamacpp': 'llamacpp-embedding',
    'vllm': 'vllm-embedding',
    'openai': 'openai-embedding',
    'zhipu': 'zhipu-embedding',
    'minimax': 'minimax-embedding',
    'tencent': 'tencent-embedding',
    'volcengine': 'volcengine-embedding',
    'silicon': 'silicon-embedding',
    'azure_openai': 'azure-embedding',
    'qwen': 'qwen-embedding',
    'qianfan': 'qianfan-embedding'
  };
  
  // 获取指定模型类型和模型类别的模板
  export const getAdvancedParamsTemplate = (modelType: string, modelCategory: 'llm' | 'embedding'): AdvancedParams => {

    // 根据模型类别选择对应的映射表
    const templateMap = modelCategory === 'llm' ? llmModelTypeToTemplateKey : embeddingModelTypeToTemplateKey;
    const templates = modelCategory === 'llm' ? llmTemplates : embeddingTemplates;
    
    // 查找对应的模板键，默认使用openai风格模板
    const templateKey = templateMap[modelType] || (modelCategory === 'llm' ? 'openai-llm' : 'openai-embedding');
    
    // 返回深拷贝的模板，避免原对象被修改
    return JSON.parse(JSON.stringify(templates[templateKey]));
  };
  
  // 将模板对象转换为格式化的JSON字符串
  export const templateToJsonString = (template: AdvancedParams): string => {
    return JSON.stringify(template, null, 2);
  };