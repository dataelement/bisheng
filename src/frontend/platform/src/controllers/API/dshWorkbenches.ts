import request from "@/controllers/request";
import type { MarketPage } from "./dshMarket";

export interface WorkbenchVersionSummary {
    id: string;
    version: string;
}

export interface MarketWorkbench {
    id: string;
    revision: number;
    identity_kind: "repository" | "legacy";
    workbench_key: string | null;
    legacy_id: string | null;
    package_name: string;
    display_name: string;
    description: string;
    current_version: WorkbenchVersionSummary;
    verification_level: "static";
    updated_at: string;
}

export type MarketWorkbenchRow = MarketWorkbench | (
    Pick<MarketWorkbench, "id" | "display_name" | "description" | "workbench_key" | "legacy_id" | "updated_at"> & {
        current_version: Pick<WorkbenchVersionSummary, "version">;
    }
);

export interface MarketWorkbenchDetail extends Omit<MarketWorkbench, "current_version"> {
    current_version: WorkbenchVersionSummary & {
        sha256: string;
        size_bytes: number;
        artifact_url: string;
    };
    package_metadata: {
        repository_url: string | null;
        patch_entry_id: string;
        server_entry: string;
        client_entry: string;
        bundle_patch: string;
        license: string | null;
        node_engine: string | null;
        dependencies: string[];
        legacy_manifest: boolean;
    };
}

export interface WorkbenchPreview {
    package_name: string;
    identity_kind: "repository" | "legacy";
    workbench_key: string | null;
    legacy_id: string | null;
    incoming_version: string;
    current_version: string | null;
    suggested_display_name: string;
    allowed: boolean;
    duplicate: boolean;
    overwrite?: boolean;
    reason: string;
    warnings: string[];
}

export interface WorkbenchImport {
    id: string;
    status: "validating" | "completed" | "failed";
    error_code: string;
    error: string;
    version_id: string | null;
    created_at: string;
}

const base = "/api/v1/dsh/market/admin/workbenches";
const tenantHeaders = (tenant: number) => ({ "x-dsh-market-tenant": String(tenant) });

export const listMarketWorkbenches = (tenant: number, page: number, signal?: AbortSignal) =>
    request.get<unknown, MarketPage<MarketWorkbenchRow>>(base, {
        params: { page, size: 20 }, signal, headers: tenantHeaders(tenant),
    });

export const deleteMarketWorkbench = (id: string, revision: number, tenant: number, signal?: AbortSignal) =>
    request.delete<unknown, { id: string; deleted: true }>(`${base}/${id}`, {
        params: { revision }, signal, headers: tenantHeaders(tenant),
    });

export const listWorkbenchImports = (tenant: number) =>
    request.get<unknown, WorkbenchImport[]>(`${base}/imports`, { headers: tenantHeaders(tenant) });

export const getMarketWorkbench = (id: string) =>
    request.get<unknown, MarketWorkbenchDetail>(`/api/v1/dsh/market/workbenches/${id}`);

export const previewWorkbenchBundle = (file: File, tenant: number, signal: AbortSignal) => {
    const body = new FormData();
    body.append("file", file);
    return request.post<unknown, WorkbenchPreview>(`${base}/imports/preview`, body, {
        signal, timeout: 300000, silent: true, headers: tenantHeaders(tenant),
    });
};

export const importWorkbenchBundle = (
    file: File, tenant: number, displayName: string, signal: AbortSignal, onProgress: (percent: number) => void,
) => {
    const body = new FormData();
    body.append("file", file);
    if (displayName.trim()) body.append("display_name", displayName.trim());
    return request.post<unknown, WorkbenchImport>(`${base}/imports`, body, {
        signal, timeout: 300000, headers: tenantHeaders(tenant),
        onUploadProgress: event => onProgress(Math.round((event.loaded / (event.total || file.size)) * 100)),
    });
};

export const resumeWorkbenchImport = (id: string, tenant: number) =>
    request.post<unknown, WorkbenchImport>(`${base}/imports/${id}/resume`, {}, { headers: tenantHeaders(tenant) });
