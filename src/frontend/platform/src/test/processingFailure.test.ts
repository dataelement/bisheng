import { expect, it } from "vitest";
import { processingFailureKey } from "@/pages/KnowledgePage/components/processingFailure";

it("explains recorded reasons and configuration expiry before generic codes", () => {
  expect(
    processingFailureKey(
      { failure_reason: "copy_permissions_changed", error_code: 10996 },
      "space_copy",
    ),
  ).toBe("f118.failure_copy_permissions_changed");
  expect(
    processingFailureKey({
      obsolete_reason: "model_config_revision_changed",
      error_code: 10997,
    }),
  ).toBe("f118.failure_model_changed");
});
it("does not invent a precise cause for old copies or render raw provider messages", () => {
  expect(processingFailureKey({ error_code: 10996 }, "space_copy")).toBe(
    "f118.failure_copy_details_missing",
  );
  expect(
    processingFailureKey({
      failure_reason: "secret/raw-provider-response",
      error_code: 10953,
    }),
  ).toBe("api_errors:10953");
});
