import { create } from 'zustand';

// 模型厂商
export interface ModelProvider {
    config: any;
    create_time: string;
    description: string;
    id: number,
    limit: number,
    limit_flag: boolean,
    models: Model[],
    name: string,
    type: string,
    update_time: string,
    user_id: number,
}

// 模型类型
export interface Model {
  /** 检查状态，布尔值 */
  check: boolean;
  /** 创建时间，ISO 格式字符串 */
  create_time: string;
  /** 模型描述，可能为空字符串 */
  description: string;
  /** 模型唯一ID，数字类型 */
  id: number;
  /** 模型技术名称（如 deepseek-chat） */
  model_name: string;
  /** 模型类型（如 llm） */
  model_type: string;
  /** 模型显示名称 */
  name: string;
  /** 是否在线，布尔值 */
  online: boolean;
  /** 备注信息，可能为空字符串 */
  remark: string;
  /** 关联的服务器ID，数字类型 */
  server_id: number;
  /** 状态码，数字类型 */
  status: number;
  /** 更新时间，ISO 格式字符串 */
  update_time: string;
  /** 关联用户ID，数字类型 */
  user_id: number;
}

export interface ModelExtra {
  // 厂家类型
  providerType: string;
  // 是否具有联网能力
  hasOnlineCapacity: boolean;
}

interface ModelStore {
  // 普通模型列表
  models: (Model & ModelExtra)[];
  // 工作流模型列表
  agentModels: (Model & ModelExtra)[];
  // 设置模型厂商列表
  setModels: (models: ModelProvider[], type: MODEL_TYPE) => void;
  // 从API获取模型列表
  fetchModels: () => Promise<void>;
  // 从API获取工作流模型列表
  fetchAgentModels: () => Promise<void>;
  getModelsTypeMap: (type: MODEL_TYPE) => {
    [key: string]: string;
  }
}

export enum MODEL_TYPE {
  MODEL = 'model',
  AGENT_MODEL = 'agentModel'
}

const useModelStore = create<ModelStore>((set, get) => ({
  models: [],
  agentModels: [],

  getModelsTypeMap: (type) => {
    const { models, agentModels } = get();
    return (type === MODEL_TYPE.MODEL ? models : agentModels).reduce((prev, curr) => {
        return {
          ...prev,
          [curr.id]: curr.providerType,
        }
    }, {})
  },

  setModels: (modelProviders, type: MODEL_TYPE) => set(() => {
    
    console.log('ModelProviders', modelProviders);
    const models = modelProviders.reduce((prev, curr) => {
        const models = [];
        curr.models.forEach(item => {
          models.push({
            ...item,
            providerType: curr.type,
            hasOnlineCapacity: ['qwen', 'tencent', 'moonshot'].includes(curr.type),
          })
        })
        return [...prev, ...models]
    }, [])
    console.log('models', models);
    
    return  {
      [type === MODEL_TYPE.MODEL ? 'models': 'agentModel']: models,
    };
  }),

  
  fetchModels: async () => {
    
  },
  
  fetchAgentModels: async () => {
  }
}));

export default useModelStore;