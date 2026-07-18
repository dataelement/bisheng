import { describe, expect, it } from "vitest";

import { resolveConfigString } from "@/pages/BuildPage/bench/configValue";

describe("resolveConfigString", () => {
  it("preserves an explicit empty string from config", () => {
    expect(resolveConfigString("", "default prompt")).toBe("");
  });

  it("preserves whitespace-only strings instead of injecting defaults", () => {
    expect(resolveConfigString("   ", "default prompt")).toBe("   ");
  });

  it("falls back only when the config value is missing", () => {
    expect(resolveConfigString(undefined, "default prompt")).toBe("default prompt");
    expect(resolveConfigString(null, "default prompt")).toBe("default prompt");
  });
});
