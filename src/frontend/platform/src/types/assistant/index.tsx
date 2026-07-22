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
    /** 知识库ID列表，为None则不更新；type 区分文档知识库(0)与知识空间(3, KnowledgeTypeEnum.SPACE) (F041) */
    knowledge_list?: { id: number, name: string, index_name?: string, type?: number }[];
    /** F041: 用户知识库权限校验开关，默认关；开=按运行使用者 view_file 过滤知识空间检索，关=按配置者可见范围 */
    knowledge_auth?: boolean;
    max_token: number;
}


export interface AssistantTool {
    id: number;
    tool_key: string;
    name: string;
}