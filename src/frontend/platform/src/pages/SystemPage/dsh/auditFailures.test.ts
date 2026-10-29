import { expect, it } from "vitest";
import { auditFailure } from "./auditFailures";

it("AC-12: preserves observed HTTP status without rendering arbitrary provider text", () => {
  expect(auditFailure("upstream_http_401", "model")).toEqual({
    key: "authentication",
    status: "401",
  });
  expect(auditFailure("upstream_http_429", "model")).toEqual({
    key: "rate_or_quota",
    status: "429",
  });
  expect(auditFailure("upstream_http_502", "model")).toEqual({
    key: "provider",
    status: "502",
  });
  expect(auditFailure("upstream_timeout", "model")).toEqual({ key: "timeout" });
  for (const code of [
    null,
    "upstream_error",
    "private provider diagnostic",
    "upstream_http_401 extra",
    "toString",
    "__proto__",
  ]) {
    expect(auditFailure(code, "model")).toEqual({ key: "unavailable" });
  }
});

it("AC-13: keeps model failures independent from transport failures", () => {
  expect(auditFailure("peer_disconnected", "response")).toEqual({
    key: "peer_disconnected",
  });
  expect(auditFailure("send_failed", "response")).toEqual({
    key: "send_failed",
  });
  expect(auditFailure("response_interrupted", "response")).toEqual({
    key: "response_interrupted",
  });
  expect(auditFailure("upstream_timeout", "response")).toEqual({
    key: "unavailable",
  });
});
