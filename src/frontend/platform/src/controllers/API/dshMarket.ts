import request from "@/controllers/request";

export interface MarketVersion {
    id: string;
    version: string;
    digest: string;
    manifest: {
        plugin: { name: string; display_name: string; description: string; publisher: string; license: string;
            desktop_min: string; permissions: string[]; services: string[]; changelog?: string };
        targets: Record<string, Record<string, string>>;
    };
}
export interface MarketPlugin {
    id: string; tenant_id: number; name: string; display_name: string; description: string;
    current_version_id: string | null; revision: number; disabled: boolean;
    updated_at: string; versions: MarketVersion[];
}
export interface MarketImport { id: string; status: "validating" | "completed" | "pending" | "failed"; error: string; created_at: string }
const tenantHeaders = (tenant: number) => ({ "x-dsh-market-tenant": String(tenant) });
const base = "/api/v1/dsh/market/admin";
export const listMarketPlugins = (params: { page: number }, tenant: number, signal?: AbortSignal) =>
    request.get<unknown, { data: MarketPlugin[]; total: number }>(`${base}/plugins`, { params, signal, headers: tenantHeaders(tenant) });
export const getMarketContext = () => request.get<unknown, { tenant_id: number }>(`${base}/context`);
export const getMarketPlugin = (id: string, tenant: number) => request.get<unknown, MarketPlugin>(`${base}/plugins/${id}`, { headers: tenantHeaders(tenant) });
export const deleteMarketPlugin = (plugin: MarketPlugin) =>
    request.delete<unknown, { id: string; deleted: boolean }>(`${base}/plugins/${plugin.id}`, { params: { revision: plugin.revision }, headers: tenantHeaders(plugin.tenant_id) });
export const listMarketImports = (tenant: number) => request.get<unknown, MarketImport[]>(`${base}/imports`, { headers: tenantHeaders(tenant) });
export const resumeMarketImport = (id: string, tenant: number) => request.post<unknown, MarketImport>(`${base}/imports/${id}/resume`, {}, { headers: tenantHeaders(tenant) });
export const importMarketBundle = (file: File, tenant: number, signal: AbortSignal, onProgress: (percent: number) => void) => {
    const body = new FormData();
    body.append("file", file);
    return request.post<unknown, MarketImport>(`${base}/imports`, body, {
        signal, timeout: 300000, headers: tenantHeaders(tenant), onUploadProgress: (event) => onProgress(Math.round((event.loaded / (event.total || file.size)) * 100)),
    });
};

export interface MarketPreview {
    name: string; display_name: string; current_version: string | null; incoming_version: string;
    allowed: boolean; reason: string; duplicate: boolean;
}
export const previewMarketBundle = (file: File, tenant: number, signal: AbortSignal) => {
    const body = new FormData(); body.append("file", file);
    return request.post<unknown, MarketPreview>(`${base}/imports/preview`, body, {
        signal, timeout: 300000, headers: tenantHeaders(tenant),
    });
};
