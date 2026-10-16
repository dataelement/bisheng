import request from "@/controllers/request";

export type ModelType = "llm" | "embedding" | "rerank" | "asr" | "tts";
export interface DiscoveredModel {
  model_name: string;
  display_name: string;
  model_type: ModelType | null;
  type_source: "metadata" | "registry" | "unknown" | "unsupported";
}
export interface DiscoveryConnection {
  provider: string;
  config: Record<string, string>;
  server_id?: number;
}
export async function discoverModels(
  connection: DiscoveryConnection,
): Promise<{ models: DiscoveredModel[] }> {
  const options = { preserveError: true, timeout: 60000 };
  return await request.post("/api/v1/llm/models/discover", connection, options);
}
