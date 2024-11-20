import { Edge, Node, ReactFlowJsonObject, Viewport, XYPosition } from "@xyflow/react";
import { APIClassType } from "../api/index";

/** 流程 */
export type FlowState = {
  edges: {
    source: string;
    target: string;
    /** 来源节点内部的唯一ID，目前只有condition节点需要 */
    source_internal_id
  }[];
  views: FlowNode[];
  viewport: any;
}

/** 流程节点 */
interface FlowNode {
  id: string;
  name: string;
  type: string;
  inputVariable: { [key: string]: any };
  outputVariable: { [key: string]: any };
  data?: {
    edges: {
      source: string;
      target: string;
    }[];
    nodes: any[];
    viewport: any;
  }
}


export type FlowType = {
  name: string;
  id: string;
  data: ReactFlowJsonObject | null;
  description: string;
  status: number;
  style?: FlowStyleType;
  user_name?: string;
  write: boolean;
  guide_word: string
  is_component?: boolean;
  parent?: string;
  date_created?: string;
  updated_at?: string;
  last_tested_version?: string;
  logo?: string;
};
export type NodeType = {
  id: string;
  type?: string;
  position: XYPosition;
  data: NodeDataType;
  selected?: boolean;
};

export type NodeDataType = {
  showNode?: boolean;
  type: string;
  node?: APIClassType;
  id: string;
  output_types?: string[];
};
// FlowStyleType is the type of the style object that is used to style the
// Flow card with an emoji and a color.
export type FlowStyleType = {
  emoji: string;
  color: string;
  flow_id: string;
};

export type TweaksType = Array<
  {
    [key: string]: {
      output_key?: string;
    };
  } & FlowStyleType
>;

// right side
export type sourceHandleType = {
  dataType: string;
  id: string;
  baseClasses: string[];
};
//left side
export type targetHandleType = {
  inputTypes?: string[];
  type: string;
  fieldName: string;
  id: string;
  proxy?: { field: string; id: string };
};


export type FlowVersionItem = {
  create_time: string;
  data: null | any; // Replace 'any' with a more specific type if known
  description: null | string;
  flow_id: string;
  id: number;
  is_current: number;
  is_delete: number;
  name: string;
  update_time: string;
  user_id: null | string;
};

export interface WorkFlow {
  id: string;
  name: string;
  description: string;
  nodes: Node[];
  edges: Edge[];
  viewport: Viewport;
  // status: number;
  // style?: FlowStyleType;
  // user_name?: string;
  // write: boolean;
  // guide_word: string;
  // is_component?: boolean;
  // parent?: string;
}

export interface WorkflowNode {
  /** node id */
  id: string;
  /** Display name */
  name: string;
  /** Description */
  description: string;
  /** Node type, */
  type: string; // 'start' | 'output' | 'code' | 'llm' | 'rag' | 'qa_retriever' | 'agent' | 'end' | 'condition' | 'input' | 'report' | 'tool';
  group_params: {
    /** group name */
    name?: string;
    /** group parameters */
    params: WorkflowNodeParam[];
  }[];

  /** tab */
  tab?: {
    /** Current value */
    value: string;
    /** options */
    options: {
      /** Display label */
      label: string;
      /** Unique key */
      key: string;
      /** help text */
      help?: string;
    }[];
  };

  /**  tool id */
  tool_id?: string;
}

export interface WorkflowNodeParam {
  /** Unique key */
  key: string;
  /** Optional display */
  label?: string;
  /** type */
  type: string;
  /** value */
  value: any;
  /** placeholder */
  placeholder?: string;
  /** help text */
  help?: string;
  /** tab */
  tab?: string;
  /** required*/
  required?: boolean;
  /**  multiple value */
  multi?: boolean;
  /** Array of options */
  options?: any[];
  test?: string
}

/** 工作流消息结构 */
export interface WorkflowMessage {
  category: string;              // "processing"
  node_id?: string;               // Node identifier
  flow_id: string;               // Flow identifier
  chat_id: string | null;        // Nullable, could be null if not set
  message_id: string | null;     // Nullable, could be null if not set
  files: any[];                  // Array, likely for file attachments
  is_bot: boolean;               // True if the sender is a bot
  liked?: boolean;                 // Count or boolean representing like status
  message: any;               // Actual message content, empty in this case
  receiver: string | null;       // Nullable receiver field
  sender: string | null;         // Nullable sender field
  source: number;                // Source identifier, type unclear
  user_id: number;               // User identifier, integer type
  end: boolean;
  update_time: string;
}