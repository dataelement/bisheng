import request from "~/api/request";
import {
  applyMenuAccessApi,
  applyDepartmentFileViewApi,
  decideApprovalTaskApi,
  getApprovalInstanceDetailApi,
  getMyApprovalTaskDetailApi,
  getDepartmentFileViewStatusApi,
  listApprovalRequestsApi,
  listMyApprovalRequestsApi,
  listMyApprovalTasksApi,
  revokeDepartmentFileViewGrantApi,
  revokeMenuAccessGrantApi,
  submitShougangKnowledgeSpaceCreateApprovalApi,
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

  it("submits withdraw and revoke grant actions", async () => {
    mockPost
      .mockResolvedValueOnce({
        status_code: 200,
        data: { instance_id: 21, status: "withdrawn" },
      })
      .mockResolvedValueOnce({
        status_code: 200,
        data: { instance_id: 21, revoked_keys: ["knowledge"] },
      });

    await expect(withdrawApprovalInstanceApi(21, { reason: "cancel" })).resolves.toEqual({
      instance_id: 21,
      status: "withdrawn",
    });
    await expect(revokeMenuAccessGrantApi(21, { reason: "cleanup" })).resolves.toEqual({
      instance_id: 21,
      revoked_keys: ["knowledge"],
    });

    expect(mockPost).toHaveBeenNthCalledWith(1, "/api/v1/approval/instances/21/withdraw", {
      reason: "cancel",
    });
    expect(mockPost).toHaveBeenNthCalledWith(2, "/api/v1/approval/menu-access/21/revoke-grant", {
      reason: "cleanup",
    });
  });

  it("revokes a department file view grant through the fixed endpoint", async () => {
    mockPost.mockResolvedValue({
      status_code: 200,
      data: { instance_id: 31, grant_status: "revoked" },
    });

    await expect(
      revokeDepartmentFileViewGrantApi(31, { reason: "权限回收" }),
    ).resolves.toEqual({
      instance_id: 31,
      grant_status: "revoked",
    });
    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/approval/department-file-view/31/revoke-grant",
      { reason: "权限回收" },
    );
  });

  it("queries status without side effects and explicitly applies for department file view", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: {
        space_id: 10,
        file_id: 20,
        status: "approval_required",
        content_access: "approval_required",
        safe_metadata: { file_name: "制度.pdf" },
      },
    });
    mockPost.mockResolvedValue({
      status_code: 200,
      data: {
        space_id: 10,
        file_id: 20,
        status: "pending",
        instance_id: 30,
      },
    });

    await expect(getDepartmentFileViewStatusApi("10", "20")).resolves.toMatchObject({
      status: "approval_required",
      safeMetadata: { file_name: "制度.pdf" },
    });
    expect(mockGet).toHaveBeenCalledWith("/api/v1/approval/department-file-view/status", {
      params: { space_id: 10, file_id: 20 },
    });
    expect(mockPost).not.toHaveBeenCalled();

    await applyDepartmentFileViewApi("10", "20", "  项目查阅  ");
    expect(mockPost).toHaveBeenCalledWith("/api/v1/approval/department-file-view/apply", {
      space_id: 10,
      file_id: 20,
      reason: "项目查阅",
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

  it("审批直通创建时将 raw space 归一化（数字 id → 字符串），供跳转/权限检查使用", async () => {
    mockPost.mockResolvedValue({
      status_code: 200,
      data: {
        decision: "auto_approved",
        created: true,
        space: { id: 162, name: "新空间", space_level: "public", user_id: 1, auth_type: "public" },
      },
    });

    const result = await submitShougangKnowledgeSpaceCreateApprovalApi({
      name: "新空间",
      description: "",
      auth_type: "public",
      is_released: false,
      space_level: "public",
    } as never);

    expect(result.created).toBe(true);
    expect(result.space?.id).toBe("162");
    expect(typeof result.space?.id).toBe("string");
    expect(result.space?.spaceLevel).toBe("public");
  });
});
