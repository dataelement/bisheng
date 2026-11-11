import request from "./request";
import { precheckMoveFilesApi, confirmMoveFilesApi } from "./knowledge";
import {
  getProcessingJob,
  listProcessingItems,
  retryProcessingJob,
} from "./knowledgeProcessing";

jest.mock("./request", () => ({
  __esModule: true,
  default: { getResponse: jest.fn(), get: jest.fn(), post: jest.fn() },
}));
const transport = request as jest.Mocked<typeof request>;
const precheck = {
  confirmation_id: "native-plan",
  plan_digest: "a".repeat(64),
  check_complete: true,
  can_execute: true,
  valid_items: [{ id: 81, type: "file" }],
  invalid_items: [],
  impact: { logical_count: 2 },
};

it("pins the real precheck and confirms only opaque fields, retaining async Accepted", async () => {
  transport.getResponse.mockResolvedValue({
    headers: { "x-management-tenant": "101" },
  });
  transport.post
    .mockResolvedValueOnce({ status_code: 200, data: precheck })
    .mockResolvedValueOnce({
      status_code: 200,
      data: {
        accepted: true,
        job_id: "actual-job",
        state: "accepted",
        reused: false,
      },
    });
  const review = await precheckMoveFilesApi("10", {
    items: [{ id: "81", type: "file" }],
    target_space_id: "11",
    target_folder_id: "51",
  });
  const accepted = await confirmMoveFilesApi("10", review, "original-key");
  expect(transport.post).toHaveBeenNthCalledWith(
    1,
    "/api/v1/knowledge/space/10/files/move/precheck",
    {
      items: [{ id: 81, type: "file" }],
      target_space_id: 11,
      target_folder_id: 51,
      skip_invalid: false,
    },
    { headers: { "X-Management-Tenant": "101" } },
  );
  expect(transport.post).toHaveBeenNthCalledWith(
    2,
    "/api/v1/knowledge/space/10/files/move/confirm",
    {
      confirmation_id: "native-plan",
      plan_digest: "a".repeat(64),
      idempotency_key: "original-key",
    },
    { headers: { "X-Management-Tenant": "101" } },
  );
  expect(accepted).toEqual({
    accepted: true,
    job_id: "actual-job",
    state: "accepted",
    reused: false,
  });
  expect(accepted).not.toHaveProperty("moved");
});

it("move query/items/retry opt in without changing ordinary default wire calls", async () => {
  transport.get.mockResolvedValue({ status_code: 200, data: {} });
  transport.post.mockResolvedValue({ status_code: 200, data: {} });
  await getProcessingJob(10, "job", "move_index");
  await listProcessingItems(10, "job", { kind: "move_index", page: 2 });
  await retryProcessingJob(
    10,
    "job",
    { idempotency_key: "retry", expected_job_revision: 7 },
    "move_index",
    "101",
  );
  expect(transport.get).toHaveBeenNthCalledWith(
    1,
    "/api/v1/knowledge/space/10/processing-jobs/job",
    { params: { kind: "move_index" } },
  );
  expect(transport.get).toHaveBeenNthCalledWith(
    2,
    "/api/v1/knowledge/space/10/processing-jobs/job/items",
    { params: { kind: "move_index", page: 2 } },
  );
  expect(transport.post).toHaveBeenCalledWith(
    "/api/v1/knowledge/space/10/processing-jobs/job/retry",
    { idempotency_key: "retry", expected_job_revision: 7 },
    {
      params: { kind: "move_index" },
      headers: { "X-Management-Tenant": "101" },
    },
  );
});

it("missing management pin fails before a move command", async () => {
  transport.getResponse.mockResolvedValue({ headers: {} });
  await expect(
    precheckMoveFilesApi("10", {
      items: [{ id: "81", type: "file" }],
      target_space_id: "11",
    }),
  ).rejects.toThrow();
  expect(transport.post).not.toHaveBeenCalled();
});
