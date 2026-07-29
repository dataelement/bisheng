import { describe, expect, it } from "vitest";

import { hasTempKnowledgeMode } from "@/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem";

describe("hasTempKnowledgeMode", () => {
  it("accepts the v3 form strategy array", () => {
    expect(hasTempKnowledgeMode(["extract_text", "ingest_to_temp_kb"])).toBe(
      true,
    );
  });

  it("accepts the legacy string strategy", () => {
    expect(hasTempKnowledgeMode("ingest_to_temp_kb")).toBe(true);
  });

  it("rejects strategies that do not ingest to the temporary knowledge base", () => {
    expect(hasTempKnowledgeMode(["extract_text"])).toBe(false);
    expect(hasTempKnowledgeMode(["keep_raw"])).toBe(false);
    expect(hasTempKnowledgeMode(undefined)).toBe(false);
  });
});
