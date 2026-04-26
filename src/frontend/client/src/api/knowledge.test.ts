import request from "~/api/request";
import { createFolderApi, getSquareSpacesApi, VisibilityType } from "./knowledge";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    postMultiPart: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;
const mockPost = request.post as jest.Mock;
const mockPostMultiPart = request.postMultiPart as jest.Mock;

describe("getSquareSpacesApi", () => {
  it("maps pending square items from is_pending when subscription_status is absent", async () => {
    mockGet.mockResolvedValue({
      data: {
        total: 1,
        data: [
          {
            space: {
              id: 101,
              name: "Pending space",
              auth_type: VisibilityType.APPROVAL,
              user_id: 7,
              user_name: "owner",
              is_released: true,
            },
            is_pending: true,
            file_num: 3,
            follower_num: 2,
          },
        ],
      },
    });

    const result = await getSquareSpacesApi();

    expect(result.data[0]).toMatchObject({
      id: "101",
      isPending: true,
      isFollowed: false,
      squareStatus: "pending",
    });
  });
});

describe("subscribeSpaceApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("returns backend subscription status", async () => {
    const { subscribeSpaceApi } = await import("./knowledge");
    mockPost.mockResolvedValue({
      status_code: 200,
      data: {
        status: "pending",
        space_id: 101,
      },
    });

    await expect(subscribeSpaceApi("101")).resolves.toEqual({
      status: "pending",
      spaceId: "101",
    });
  });
});

describe("createFolderApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("rejects backend business errors", async () => {
    mockPost.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(createFolderApi("101", { name: "New folder" })).rejects.toThrow("Permission denied");
  });
});

describe("uploadFileToServerApi", () => {
  beforeEach(() => {
    mockPostMultiPart.mockReset();
  });

  it("rejects backend business errors", async () => {
    const { uploadFileToServerApi } = await import("./knowledge");
    mockPostMultiPart.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(uploadFileToServerApi("101", new File(["x"], "doc.txt"))).rejects.toThrow("Permission denied");
  });
});

describe("addFilesApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("rejects backend business errors", async () => {
    const { addFilesApi } = await import("./knowledge");
    mockPost.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(addFilesApi("101", { file_path: ["/tmp/doc.txt"] })).rejects.toThrow("Permission denied");
  });
});
