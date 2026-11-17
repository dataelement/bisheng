export interface PlatformModelReference {
    resource_id: string;
    version_id: string;
    call_id: string;
    name?: string;
    version?: string;
}

export interface PlatformModelSummary extends PlatformModelReference {
    resource_type: string;
    description?: string;
    status: string;
    allowed_actions: string[];
}

export interface PlatformModelCapabilities {
    platform_llm_enabled: boolean;
    multi_tenant_enabled?: boolean;
}

export interface PlatformModelListPage {
    items: PlatformModelSummary[];
    page_size: number;
    has_more: boolean;
    next_cursor: string | null;
}
