import request from "~/api/request";
import { authorizeResource } from "./permission";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockPost = request.post as jest.Mock;

describe("permission API", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("rejects business error envelopes from authorizeResource", async () => {
    mockPost.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(
      authorizeResource(
        "knowledge_space",
        "1",
        [{ subject_type: "user", subject_id: 2, relation: "viewer" }],
        [],
      ),
    ).rejects.toThrow("Permission denied");
  });
});
