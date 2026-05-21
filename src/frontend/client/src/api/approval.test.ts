import request from "~/api/request";
import {
  applyMenuAccessApi,
  decideApprovalTaskApi,
  getApprovalInstanceDetailApi,
  getMyApprovalTaskDetailApi,
  listApprovalRequestsApi,
  listMyApprovalRequestsApi,
  listMyApprovalTasksApi,
  revokeMenuAccessGrantApi,
  resubmitApprovalInstanceApi,
  withdrawApprovalInstanceApi,
} from "./approval";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    paramsSerializer: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;
const mockPost = request.post as jest.Mock;

describe("approval api", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it("uses repeated query params for legacy approval request status arrays", async () => {
    mockGet.mockResolvedValue({ data: [], total: 0 });

    await listApprovalRequestsApi({
      space_id: 1,
      statuses: ["pending_review", "rejected", "finalize_failed"],
      page: 1,
      page_size: 100,
    });

    expect(mockGet).toHaveBeenCalledWith("/api/v1/approval/requests", {
      params: {
        space_id: 1,
        statuses: ["pending_review", "rejected", "finalize_failed"],
        page: 1,
        page_size: 100,
      },
      paramsSerializer: request.paramsSerializer,
    });
  });

  it("unwraps my-task list payloads from approval center", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: { data: [{ task_id: 11, business_name: "知识库订阅" }], total: 1 },
    });

    await expect(listMyApprovalTasksApi()).resolves.toEqual({
      data: [{ task_id: 11, business_name: "知识库订阅" }],
      total: 1,
    });
  });

  it("loads task detail from approval center endpoint", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: { task_id: 11, status: "pending" },
    });

    await expect(getMyApprovalTaskDetailApi(11)).resolves.toEqual({
      task_id: 11,
      status: "pending",
    });
  });

  it("submits task decisions to approval center endpoint", async () => {
    mockPost.mockResolvedValue({
      status_code: 200,
      data: { task_id: 11, status: "approved" },
    });

    await expect(decideApprovalTaskApi(11, { action: "approve", comment: "ok" })).resolves.toEqual({
      task_id: 11,
      status: "approved",
    });
    expect(mockPost).toHaveBeenCalledWith("/api/v1/approval/tasks/11/decision", {
      action: "approve",
      comment: "ok",
    });
  });

  it("unwraps my-request list payloads from approval center", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: { data: [{ instance_id: 21, business_name: "频道订阅" }], total: 1 },
    });

    await expect(listMyApprovalRequestsApi()).resolves.toEqual({
      data: [{ instance_id: 21, business_name: "频道订阅" }],
      total: 1,
    });
  });

  it("loads approval instance detail", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: { instance_id: 21, status: "approved" },
    });

    await expect(getApprovalInstanceDetailApi(21)).resolves.toEqual({
      instance_id: 21,
      status: "approved",
    });
  });

  it("submits withdraw, resubmit and revoke grant actions", async () => {
    mockPost
      .mockResolvedValueOnce({
        status_code: 200,
        data: { instance_id: 21, status: "withdrawn" },
      })
      .mockResolvedValueOnce({
        status_code: 200,
        data: { instance_id: 21, status: "pending" },
      })
      .mockResolvedValueOnce({
        status_code: 200,
        data: { instance_id: 21, revoked_keys: ["knowledge"] },
      });

    await expect(withdrawApprovalInstanceApi(21, { reason: "cancel" })).resolves.toEqual({
      instance_id: 21,
      status: "withdrawn",
    });
    await expect(resubmitApprovalInstanceApi(21, { reason: "retry" })).resolves.toEqual({
      instance_id: 21,
      status: "pending",
    });
    await expect(revokeMenuAccessGrantApi(21, { reason: "cleanup" })).resolves.toEqual({
      instance_id: 21,
      revoked_keys: ["knowledge"],
    });

    expect(mockPost).toHaveBeenNthCalledWith(1, "/api/v1/approval/instances/21/withdraw", {
      reason: "cancel",
    });
    expect(mockPost).toHaveBeenNthCalledWith(2, "/api/v1/approval/instances/21/resubmit", {
      reason: "retry",
    });
    expect(mockPost).toHaveBeenNthCalledWith(3, "/api/v1/approval/menu-access/21/revoke-grant", {
      reason: "cleanup",
    });
  });

  it("submits menu access applications", async () => {
    mockPost.mockResolvedValue({
      status_code: 200,
      data: { decision: "pending", instance_id: 31 },
    });

    await expect(applyMenuAccessApi({
      menu_key: "knowledge_space",
      menu_name: "知识库",
    })).resolves.toEqual({
      decision: "pending",
      instance_id: 31,
    });

    expect(mockPost).toHaveBeenCalledWith("/api/v1/approval/menu-access/apply", {
      menu_key: "knowledge_space",
      menu_name: "知识库",
    });
  });
});
