import request from "./request";

export interface EffectiveQuotaItem {
    resource_type: string;
    role_quota: number;
    tenant_quota: number;
    tenant_used: number;
    user_used: number;
    /** -1 = unlimited */
    effective: number;
}

// Fetch the current user's effective quota (role + tenant) for all resource types.
export async function getEffectiveQuotaApi(): Promise<EffectiveQuotaItem[]> {
    const resp: any = await request.get("/api/v1/quota/effective");
    // request.get returns the unified envelope (response.data); items live under .data.
    return resp?.data ?? resp ?? [];
}
