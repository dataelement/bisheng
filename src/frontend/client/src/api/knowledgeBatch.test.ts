import request from "./request";
import { inspectBatch, precheckBatch, confirmBatch } from "./knowledgeBatch";
jest.mock("./request", () => ({ __esModule: true, default: { postResponse: jest.fn() } }));
const response = (tenant = "101") => ({
  headers: { "x-management-tenant": tenant },
  data: { status_code: 200, status_message: "ok", data: {} },
});
const command = {
  spaceId: 3,
  operation: "download" as const,
  items: [{ id: 7, type: "file" as const, name: "visible-name" }],
};
beforeEach(() => jest.mocked(request.postResponse).mockResolvedValue(response()));
it("learns pin only from same-action inspection and strips local display metadata", async () => {
  expect((await inspectBatch(command)).tenant).toBe("101");
  expect(request.postResponse).toHaveBeenCalledWith(
    "/api/v1/knowledge/space/3/files/batch/download/inspect",
    { items: [{ id: 7, type: "file" }] },
  );
});
it("binds precheck and exact three-field confirmation to that pin", async () => {
  await precheckBatch(command, "101");
  expect(request.postResponse).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/3/files/batch/download/precheck",
    { items: [{ id: 7, type: "file" }] },
    { headers: { "X-Management-Tenant": "101" } },
  );
  const confirmation = {
    confirmation_id: "plan",
    plan_digest: "hash",
    idempotency_key: "batch:plan",
  };
  await confirmBatch(command, confirmation, "101");
  expect(request.postResponse).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/3/files/batch/download/confirm",
    confirmation,
    { headers: { "X-Management-Tenant": "101" } },
  );
});
it("refuses a response from a changed management scope", async () => {
  jest.mocked(request.postResponse).mockResolvedValue(response("202"));
  await expect(precheckBatch(command, "101")).rejects.toMatchObject({ status_code: 19704 });
});
