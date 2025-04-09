import { Edge, Node, Viewport } from "@xyflow/react";
import { FlowType } from "../flow";
//kind and class are just representative names to represent the actual structure of the object received by the API
export type APIDataType = { [key: string]: APIKindType };
export type APIObjectType = { [key: string]: APIKindType };
export type APIKindType = { [key: string]: APIClassType };
export type APITemplateType = {
  [key: string]: TemplateVariableType;
};

export type CustomFieldsType = {
  [key: string]: Array<string>;
};

export type APIClassType = {
  base_classes: Array<string>;
  description: string;
  template: APITemplateType;
  display_name: string;
  icon?: string;
  input_types?: Array<string>;
  output_types?: Array<string>;
  custom_fields?: CustomFieldsType;
  beta?: boolean;
  documentation: string;
  error?: string;
  official?: boolean;
  flow?: FlowType;
  [key: string]:
    | Array<string>
    | string
    | APITemplateType
    | boolean
    | FlowType
    | CustomFieldsType
    | boolean
    | undefined;
};

export type TemplateVariableType = {
  type: string;
  required: boolean;
  placeholder?: string;
  list: boolean;
  show: boolean;
  readonly?: boolean;
  multiline?: boolean;
  value?: any;
  dynamic?: boolean;
  proxy?: { id: string; field: string };
  input_types?: Array<string>;
  display_name?: string;
  name?: string;
  [key: string]: any;
};
export type sendAllProps = {
  nodes?: Node[];
  edges?: Edge[];
  name: string;
  description: string;
  viewport?: Viewport;
  inputs: any;
  id?: string;
  file_path?: string;
  action?: string;
  chatHistory: { message: string | object; isSend: boolean }[];
  flow_id: string;
  chat_id: string;
};
export type errorsTypeAPI = {
  function: { errors: Array<string> };
  imports: { errors: Array<string> };
};
export type PromptTypeAPI = {
  input_variables: Array<string>;
  frontend_node: APIClassType;
};

export type BuildStatusTypeAPI = {
  built: boolean;
};

export type InitTypeAPI = {
  flowId: string;
};

export type UploadFileTypeAPI = {
  file_path: string;
  flowId: string;
};

export type Component = {
  name: string;
  description: string;
  data: Object;
  tags: [string];
};

export type RTServer = {
  update_time: string;
  endpoint: string;
  sft_endpoint: string;
  remark: string;
  create_time: string;
  server: string;
  id: number;
}
