export type KnowledgeQuestion =
    | { source: 'constant'; value: string }
    | { source: 'variable'; variable: string };

export interface KnowledgeReference {
    resource_id: string;
}

export interface KnowledgeResource extends KnowledgeReference {
    name: string;
    status: string;
    provider_mode: string;
}

export interface KnowledgeCapabilities {
    platform_knowledge_enabled: boolean;
    platform_knowledge_mode: string;
    platform_knowledge_connection_id: string;
    platform_knowledge_policy_revision: string;
    multi_tenant_enabled?: boolean;
}
