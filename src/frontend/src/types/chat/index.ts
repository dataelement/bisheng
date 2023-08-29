import { ReactFlowInstance } from "reactflow";
import { FlowType } from "../flow";

export type ChatType = { flow: FlowType; reactFlowInstance: ReactFlowInstance };
export type ChatMessageType = {
  message: string | Object;
  template?: string;
  isSend: boolean;
  thought?: string;
  category?: string;
  files?: Array<{ data: string; type: string; data_type: string, file_name?: string }>;
  chatKey: string;
  /** 用户打字机控制光标展示 */
  end: boolean;
  id?: number;
};
