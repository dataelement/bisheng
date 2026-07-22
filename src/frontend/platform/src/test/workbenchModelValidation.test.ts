import { describe, expect, it } from "vitest";

import { hasValidWorkbenchEmbeddingModelId } from "@/pages/ModelPage/manage/tabs/workbenchModelValidation";

describe("hasValidWorkbenchEmbeddingModelId", () => {
  it.each([null, undefined, "", "null", "undefined", "0", "-1", 0, -1])(
    "rejects an empty or invalid model id: %s",
    (value) => {
      expect(hasValidWorkbenchEmbeddingModelId(value)).toBe(false);
    },
  );

  it.each([1, 42, "1", "42"])("accepts a positive model id: %s", (value) => {
    expect(hasValidWorkbenchEmbeddingModelId(value)).toBe(true);
  });
});
