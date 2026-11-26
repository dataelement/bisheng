import type { MemorySource } from "~/api/memory";
import { memorySourceLabel } from "../memoryLabels";

const localize = (key: string, options?: Record<string, unknown>) =>
  options ? `${key}(${JSON.stringify(options)})` : key;

const source = (over: Partial<MemorySource>): MemorySource => ({
  scene: "daily",
  app_id: null,
  app_name: null,
  chat_id: "c-1",
  origin: "explicit",
  ...over,
});

describe("memorySourceLabel", () => {
  it("labels an item added by hand as manual", () => {
    expect(memorySourceLabel(source({ scene: "manual", origin: "manual", chat_id: null }), localize)).toBe(
      "memory.source.manual",
    );
  });

  it("keeps the original scene after the item is edited or revised by AI", () => {
    // Edit and AI revise keep the scene and only switch origin to manual.
    expect(memorySourceLabel(source({ origin: "manual" }), localize)).toBe("memory.source.daily");
    expect(
      memorySourceLabel(source({ scene: "assistant", app_name: "Travel Helper", origin: "manual" }), localize),
    ).toBe("memory.source.assistant · Travel Helper");
  });

  it("marks auto-consolidated items", () => {
    expect(memorySourceLabel(source({ origin: "auto" }), localize)).toBe(
      'memory.source.auto({"source":"memory.source.daily"})',
    );
  });

  it("falls back to manual when the source is missing", () => {
    expect(memorySourceLabel(null, localize)).toBe("memory.source.manual");
  });
});
