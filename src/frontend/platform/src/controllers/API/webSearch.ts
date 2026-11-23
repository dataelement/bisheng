import request from '../request';
import type { OpenApiSchemaSource } from './tools';

export type WebSearchSecret = { action: 'keep' | 'clear' } | { action: 'replace'; value: string };
export interface WebSearchSettings {
    revision: string; enabled: boolean; type: string; prompt: string;
    providers: Record<string, unknown>; custom_secret_configured: boolean;
}
export interface SearchParameter { name: string; location: string; type: string; required: boolean; schema?: Record<string, unknown> }
export interface SearchProof { key_id: string; ciphertext: string }
export interface SearchOperation { version?: number; declaration?: Record<string, unknown>; media_type?: string; request?: Record<string, unknown>; server: string; method: string; path: string; parameters: SearchParameter[]; proof: SearchProof; security: { location: 'query' | 'header' | 'cookie'; name: string } | null }
const base = (id: string) => `/api/v1/tool/${encodeURIComponent(id)}/web-search`;
export const getWebSearchSettings = async (id: string): Promise<WebSearchSettings> => request.get(`${base(id)}/settings`);
export const putWebSearchSettings = async (id: string, data: Omit<WebSearchSettings, 'custom_secret_configured'> & { custom_secret: WebSearchSecret }): Promise<WebSearchSettings> => request.put(`${base(id)}/settings`, data);
export const parseWebSearchSchema = async (id: string, source: OpenApiSchemaSource): Promise<{ operations: SearchOperation[] }> => request.post(`${base(id)}/schema`, 'file_content' in source ? { content: source.file_content } : { url: source.download_url });
export const testWebSearch = async (id: string, data: { draft: unknown; query: string; secret: Exclude<WebSearchSecret, { action: 'clear' }> }): Promise<{ status: string; preview: unknown; results: unknown }> => request.post(`${base(id)}/test`, data);
