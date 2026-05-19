import axios from "../request";

export const KNOWLEDGE_SPACE_FILE_PARSE_POLICY = "knowledge_space_file_parse";
export const CHANNEL_ARTICLE_POLICY = "channel_article";

export type SensitiveWordType = "builtin" | "custom";

export interface SensitiveWordPolicy {
    tenant_id: number;
    business_type: string;
    scope_type: string;
    scope_id: string;
    enabled: boolean;
    words_types: SensitiveWordType[];
    custom_words: string;
    auto_reply: string;
    extra_config: Record<string, unknown>;
}

export interface SensitiveWordPolicyPayload {
    enabled: boolean;
    words_types: SensitiveWordType[];
    custom_words: string;
    auto_reply?: string;
    extra_config?: Record<string, unknown>;
}

export function getSensitiveWordPolicyApi(businessType = KNOWLEDGE_SPACE_FILE_PARSE_POLICY) {
    return axios.get(`/api/v1/sensitive-word-policies/${businessType}`);
}

export function updateSensitiveWordPolicyApi(
    data: SensitiveWordPolicyPayload,
    businessType = KNOWLEDGE_SPACE_FILE_PARSE_POLICY,
) {
    return axios.put(`/api/v1/sensitive-word-policies/${businessType}`, data);
}
