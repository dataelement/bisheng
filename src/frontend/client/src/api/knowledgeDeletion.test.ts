import request from "./request";
import {
  readDeletionTenant,
  precheckDeletion,
  confirmDeletion,
  getDeletionStatus,
  pageReferences,
} from "./knowledgeDeletion";
jest.mock("./request", () => ({
  __esModule: true,
  default: { getResponse: jest.fn(), postResponse: jest.fn() },
}));
const envelope = (data: unknown, tenant = "8") => ({
  headers: { "x-management-tenant": tenant },
  data: { status_code: 200, status_message: "ok", data },
});
const command = { spaceId: 3, kind: "files", items: [{ id: 7, type: "file" }] } as const;
beforeEach(() => jest.clearAllMocks());
it("learns the tenant without requiring every selected action or root visibility", async () => {
  jest.mocked(request.postResponse).mockResolvedValue(envelope({ permitted_selection_count: 0 }));
  const captured = await readDeletionTenant(command);
  expect(captured.tenant).toBe("8");
  expect(request.postResponse).toHaveBeenCalledWith("/api/v1/knowledge/space/3/files/delete/inspect", {
    items: command.items,
  });
  expect(captured.inspection).toBeUndefined();
  expect(request.getResponse).not.toHaveBeenCalled();
});
it("sends the same real tenant through precheck, exact confirmation, status and source pages", async () => {
  jest.mocked(request.postResponse).mockResolvedValue(envelope({}));
  jest.mocked(request.getResponse).mockResolvedValue(envelope({}));
  await precheckDeletion(command, false, "8");
  expect(request.postResponse).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/3/files/delete/precheck",
    { items: command.items },
    { headers: { "X-Management-Tenant": "8" } },
  );
  const body = { idempotency_key: "delete:plan", confirmation_id: "plan", plan_digest: "hash" };
  await confirmDeletion(3, body, "8");
  expect(request.postResponse).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/3/deletion/confirm",
    body,
    { headers: { "X-Management-Tenant": "8" } },
  );
  await getDeletionStatus(3, "plan", "8");
  expect(request.getResponse).toHaveBeenLastCalledWith("/api/v1/knowledge/space/3/deletion/plan", {
    params: undefined,
    headers: { "X-Management-Tenant": "8" },
  });
  await pageReferences(command, "cursor", "8");
  expect(request.postResponse).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/3/files/references",
    { items: command.items, cursor: "cursor" },
    { headers: { "X-Management-Tenant": "8" } },
  );
});
it("rejects a changed response tenant and never fabricates one when absent", async () => {
  jest.mocked(request.getResponse).mockResolvedValue(envelope({}, "9"));
  await expect(getDeletionStatus(3, "plan", "8")).rejects.toMatchObject({ status_code: 19704 });
  jest.mocked(request.postResponse).mockResolvedValue(envelope({}, ""));
  await expect(readDeletionTenant(command)).rejects.toMatchObject({ status_code: 19704 });
});
