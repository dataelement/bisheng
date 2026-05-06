import request from "~/api/request";
import { listApprovalRequestsApi } from "./approval";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    paramsSerializer: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;

describe("listApprovalRequestsApi", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("uses repeated query params for approval status arrays", async () => {
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
});
