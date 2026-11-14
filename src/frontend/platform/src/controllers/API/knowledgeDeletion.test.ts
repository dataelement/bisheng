import { beforeEach, expect, it, vi } from "vitest";
import request from "@/controllers/request";
import {
  acceptManagementScope,
  managementRequestScope,
  requiresManagementScope,
} from "../managementScope";
import {
  confirmDeletion,
  inspectReferences,
  pageReferences,
  precheckDeletion,
} from "./knowledgeDeletion";
vi.mock("@/controllers/request", () => ({ default: { post: vi.fn(), get: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
it("preserves the three confirmation fields and distinct reference page protocol", async () => {
  const body = { idempotency_key: "delete:plan", confirmation_id: "plan", plan_digest: "hash" };
  await confirmDeletion(3, body);
  expect(request.post).toHaveBeenCalledWith("/api/v1/knowledge/space/3/deletion/confirm", body);
  await inspectReferences({ spaceId: 3, kind: "delete" });
  expect(request.get).toHaveBeenLastCalledWith("/api/v1/knowledge/space/3/references", {
    params: undefined,
  });
  await pageReferences({ spaceId: 3, kind: "files", items: [{ id: 5, type: "folder" }] }, "cursor");
  expect(request.post).toHaveBeenLastCalledWith("/api/v1/knowledge/space/3/files/references", {
    items: [{ id: 5, type: "folder" }],
    cursor: "cursor",
  });
  await expect(precheckDeletion({ spaceId: 3, kind: "clear" }, true)).rejects.toThrow(
    "invalid_force",
  );
});
it("pins all new reads and writes with the current server-learned management scope", () => {
  acceptManagementScope(8);
  expect(managementRequestScope()).toBe(8);
  for (const [method, suffix] of [
    ["GET", "references"],
    ["GET", "deletion/plan"],
    ["POST", "files/references"],
    ["POST", "files/delete/precheck"],
    ["POST", "clear/precheck"],
    ["POST", "delete/precheck"],
    ["POST", "deletion/confirm"],
  ])
    expect(requiresManagementScope(method, `/api/v1/knowledge/space/3/${suffix}`)).toBe(true);
  expect(requiresManagementScope("GET", "/api/v1/knowledge/space/3/children")).toBe(false);
  expect(
    requiresManagementScope("POST", "/api/v1/knowledge/space/3/deletion/confirm?purpose=approval"),
  ).toBe(false);
  acceptManagementScope(null);
});
