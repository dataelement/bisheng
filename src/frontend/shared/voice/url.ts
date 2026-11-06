export function getAsrWebSocketUrl(baseUrl: string, origin: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  const url = new URL(`${base}/api/v1/llm/workbench/asr/ws`, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
