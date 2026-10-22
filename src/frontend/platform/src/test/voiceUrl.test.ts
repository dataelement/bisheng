import { describe, expect, it } from "vitest";
import { getAsrWebSocketUrl } from "../../../shared/voice/url";

describe("ASR websocket deployment routes", () => {
  it.each(["/workspace", "/workspace/"])(
    "routes the client base %s through the workspace API proxy",
    (base) => {
      expect(getAsrWebSocketUrl(base, "http://localhost:13007")).toBe(
        "ws://localhost:13007/workspace/api/v1/llm/workbench/asr/ws",
      );
    },
  );

  it.each(["", "/"])("routes the platform base %s through the API proxy", (base) => {
    expect(getAsrWebSocketUrl(base, "http://192.168.106.119:3007")).toBe(
      "ws://192.168.106.119:3007/api/v1/llm/workbench/asr/ws",
    );
  });

  it("uses encrypted websockets on HTTPS deployments", () => {
    expect(getAsrWebSocketUrl("/workspace", "https://bisheng.example:8443")).toBe(
      "wss://bisheng.example:8443/workspace/api/v1/llm/workbench/asr/ws",
    );
  });
});
