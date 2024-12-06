import { ReactFlowInstance } from "@xyflow/react";
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
};
