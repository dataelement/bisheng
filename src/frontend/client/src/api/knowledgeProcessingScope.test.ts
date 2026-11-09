import request from "./request";
import { listProcessingJobs, getProcessingJob, listProcessingItems, retryProcessingJob } from "./knowledgeProcessing";
jest.mock("./request", () => ({ __esModule: true, default: { get: jest.fn(), getResponse: jest.fn(), post: jest.fn(), postResponse: jest.fn() } }));
const transport = request as jest.Mocked<typeof request>;
const response = (data: unknown, tenant = "101") => ({ data: { status_code: 200, data }, headers: { "x-management-tenant": tenant } });
beforeEach(() => jest.clearAllMocks());
it("learns the actual authorized list tenant and pins detail/items reads", async () => {
  transport.getResponse.mockResolvedValue(response({ data: [], total: 0 }));
  const onTenant = jest.fn(), signal = new AbortController().signal;
  await listProcessingJobs(3, { page: 1, page_size: 20 }, { onTenant, signal });
  expect(onTenant).toHaveBeenCalledWith("101");
  await getProcessingJob(3, "job", "file_reprocess", { tenant: "101", signal });
  await listProcessingItems(3, "job", { kind: "file_reprocess", page: 2 }, { tenant: "101", signal });
  expect(transport.getResponse).toHaveBeenNthCalledWith(2, "/api/v1/knowledge/space/3/processing-jobs/job", { params: { kind: "file_reprocess" }, signal, headers: { "X-Management-Tenant": "101" } });
  expect(transport.getResponse).toHaveBeenNthCalledWith(3, "/api/v1/knowledge/space/3/processing-jobs/job/items", { params: { kind: "file_reprocess", page: 2 }, signal, headers: { "X-Management-Tenant": "101" } });
  expect(transport.get).not.toHaveBeenCalled();
});
it("refuses a changed or missing tenant without reporting a retry acknowledgement", async () => {
  transport.getResponse.mockResolvedValue(response({}, "202"));
  await expect(getProcessingJob(3, "job", "file_reprocess", { tenant: "101" })).rejects.toMatchObject({ status_code: 19704 });
  const command = { idempotency_key: "fixed", expected_job_revision: 4 };
  transport.postResponse.mockResolvedValue(response({ job_id: "job", accepted: true }, "202"));
  await expect(retryProcessingJob(3, "job", command, "file_reprocess", "101", { tenant: "101" })).rejects.toMatchObject({ status_code: 19704 });
  expect(transport.postResponse).toHaveBeenCalledWith("/api/v1/knowledge/space/3/processing-jobs/job/retry", command, { params: { kind: "file_reprocess" }, headers: { "X-Management-Tenant": "101" }, signal: undefined });
});
