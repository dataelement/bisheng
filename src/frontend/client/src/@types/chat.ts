// 技能&工作流详情
export interface FlowData {
  create_time: string; // ISO 8601 format date string
  data: {
    edges: any[]; // Replace 'any' with a more specific type if you know the structure
    nodes: any[]; // Replace 'any' with a more specific type if you know the structure
    viewport: Record<string, unknown>; // Or a more specific type if viewport structure is known
  };
  description: string;
  flow_type: number;
  guide_word: null | string; // Assuming it can be null or string
  id: string;
  logo: string;
  name: string;
  status: number;
  update_time: string; // ISO 8601 format date string
  user_id: null | string; // Assuming it can be null or string
}

//
export type ChatMessageType = {
  message: string | Object;
  template?: string;
  isSend: boolean;
  thought?: string;
  category?: string;
  files?: Array<{ data: string; type: string; data_type: string, file_name?: string }>;
  chatKey: string;
  end: boolean;
  id?: number;
  source?: number;
  noAccess?: boolean;
  user_name: string;
  at?: string;
  /** 用户名 */
  sender?: string;
  /** @某人 */
  receiver?: any;
  liked?: boolean;
  extra?: string;
  create_time: string;
  update_time: string;
  reasoning_log?: string;
};

export interface ChatVersion {
  id: string
  name: string
  createdAt: number
  updatedAt: number
}

export interface Chat {
  flow: FlowData,
  messages: ChatMessageType[],
  /* 没有更多历史消息 */
  historyEnd: boolean
}

export interface SubmitData {
  input?: string,
  action: string,
  chatId?: string,
  flowId?: string,
  nodeId?: string,
  msgId?: string,
  data?: any,
  flow?: FlowData,
  files?: any[]
}

export interface WebSocketStatus {
  connected: boolean
  connecting: boolean
  error: string | null
}

// 运行状态
export interface RunningStatus {
  /** 是否正在运行 */
  running: boolean;
  /** 输入框禁用状态 */
  inputDisabled: boolean;
  /** 失败原因 */
  error: string;
  /** 展示form表单 */
  inputForm: any;
  /** 展示上传按钮 */
  showUpload: boolean;
  /** 展示stop按钮 */
  showStop: boolean;
  /** 引导词 */
  guideWord?: string[];
}

// 毕昇配置
export type BishengConfig = {
  env: string;
  uns_support: string[];
  office_url: string;
  dialog_tips: string;
  dialog_quick_search: string;
  websocket_url: string;
  pro: boolean;
  sso: boolean;
  application_usage_tips: boolean;
  show_github_and_help: boolean;
  version: string;
  /** 注册入口 */
  enable_registration: boolean;
  /** 最大上传文件大小 mb */
  uploaded_files_maximum_size: number;
  /** 是否部署 ETL4LM  */
  enable_etl4lm: boolean;
};
