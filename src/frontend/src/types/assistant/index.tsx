import { FlowType } from "../flow";

export interface AssistantDetail {
    /** 助手ID */
    id: number;
    /** 助手名称，为空则不更新 */
    name?: string;
    /** 助手描述，为空则不更新 */
    desc?: string;
    /** logo文件的相对地址，为空则不更新 */
    logo?: string;
    /** 用户可见的prompt，为空则不更新 */
    prompt?: string;
    /** 开场白，为空则不更新 */
    guide_word?: string;
    /** 引导问题列表，为空则不更新 */
    guide_question?: string[]; // 更具体的类型可能需要根据实际对象结构定义
    /** 选择的模型名，为空则不更新 */
    model_name?: string | number;
    /** 模型温度，为0则不更新 */
    temperature?: number;
    /** 助手的状态 */
    status: number;
    /** 用户ID */
    user_id: number;
    /** 创建时间 */
    create_time: string;
    /** 更新时间 */
    update_time: string;
    /** 内容安全审查对象 */
    // content_security: object;
    /** 助手的工具ID列表, 空列表则清空绑定的工具，为None则不更新 */
    tool_list?: AssistantTool[];
    /** 助手的技能ID列表，为None则不更新 */
    flow_list?: FlowType[];
    /** 知识库ID列表，为None则不更新 */
    knowledge_list?: { id: number, name: string, index_name: string }[];
}


export interface AssistantTool {
    id: number;
    tool_key: string;
    name: string;
}