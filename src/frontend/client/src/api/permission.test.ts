import request from "~/api/request";
import { authorizeResource, checkPermission, getGrantableRelationModels } from "./permission";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockPost = request.post as jest.Mock;
const mockGet = request.get as jest.Mock;

describe("permission API", () => {
  beforeEach(() => {
    mockPost.mockReset();
    mockGet.mockReset();
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

  it("coerces a numeric object_id to string for /permissions/check", async () => {
    mockPost.mockResolvedValue({ status_code: 200, data: { allowed: true } });

    // 新建空间返回的 raw id 可能是数字；接口要求字符串，否则后端报错
    await checkPermission("knowledge_space", 162 as unknown as string, "manager");

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/permissions/check",
      expect.objectContaining({ object_id: "162", object_type: "knowledge_space", relation: "manager" }),
      expect.anything(),
    );
  });

  it("dedupes/caches grantable requests for the same object (文件列表逐行不重复请求)", async () => {
    mockGet.mockResolvedValue({ status_code: 200, data: [{ id: 1, relation: "manager" }] });

    // 并发两次 + 之后再一次：应只发一个真实请求（in-flight 去重 + 短缓存）
    const [a, b] = await Promise.all([
      getGrantableRelationModels("folder", "dedupe-1"),
      getGrantableRelationModels("folder", "dedupe-1"),
    ]);
    const c = await getGrantableRelationModels("folder", "dedupe-1");

    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
    expect(c).toEqual(a);
  });
});
