import request from "@/controllers/request";

export type ModelType = "llm" | "embedding" | "rerank" | "asr" | "asr_rt" | "tts";
export interface DiscoveredModel {
  model_name: string;
  display_name: string;
  model_type: ModelType | null;
  type_source: "metadata" | "registry" | "unknown" | "unsupported";
}
export type DiscoverySource = "auto" | "live" | "preset";
export interface DiscoveryResult {
  models: DiscoveredModel[];
  source?: "live" | "preset";
  scope?: "catalog" | "local" | "deployments" | "azure_models";
  docs_url?: string;
  catalog_date?: string;
}
export interface DiscoveryConnection {
  provider: string;
  config: Record<string, string>;
  server_id?: number;
  source?: DiscoverySource;
  options?: Record<string, string>;
}
export async function discoverModels(
  connection: DiscoveryConnection,
): Promise<DiscoveryResult> {
  const options = { preserveError: true, timeout: 60000 };
  return await request.post("/api/v1/llm/models/discover", connection, options);
}
