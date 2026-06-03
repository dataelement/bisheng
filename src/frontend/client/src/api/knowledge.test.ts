import request from "~/api/request";
import {
  FileType,
  SpaceLevel,
  VisibilityType,
  batchDeleteApi,
  batchDownloadApi,
  createFolderApi,
  deleteFolderApi,
  getSquareSpacesApi,
  listMyUploadedFilesApi,
  mapChild,
  moveUploadedFileFolderApi,
  renameFolderApi,
  recommendUploadFoldersApi,
} from "./knowledge";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    postMultiPart: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;
const mockPost = request.post as jest.Mock;
const mockPostMultiPart = request.postMultiPart as jest.Mock;
const mockPut = request.put as jest.Mock;
const mockDelete = request.delete as jest.Mock;

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

describe("renameFolderApi", () => {
  beforeEach(() => {
    mockPut.mockReset();
  });

  it("rejects backend business errors", async () => {
    mockPut.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(renameFolderApi("101", "202", "Renamed")).rejects.toThrow("Permission denied");
  });
});

describe("deleteFolderApi", () => {
  beforeEach(() => {
    mockDelete.mockReset();
  });

  it("rejects backend business errors", async () => {
    mockDelete.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(deleteFolderApi("101", "202")).rejects.toThrow("Permission denied");
  });
});

describe("batchDeleteApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("rejects backend business errors", async () => {
    mockPost.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(batchDeleteApi("101", { folder_ids: [202] })).rejects.toThrow("Permission denied");
  });
});

describe("batchDownloadApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("rejects backend business errors", async () => {
    mockPost.mockResolvedValue({
      status_code: 19000,
      status_message: "Permission denied",
      data: null,
    });

    await expect(batchDownloadApi("101", { folder_ids: [202] })).rejects.toThrow("Permission denied");
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

describe("recommendUploadFoldersApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("posts local file ids and returns folder recommendations", async () => {
    mockPost.mockResolvedValue({
      status_code: 200,
      data: {
        items: [
          {
            client_file_id: "local-1",
            file_name: "能源管理标准.pdf",
            recommended_folder_id: 37,
            recommended_folder_name: "能源管理",
            recommended_folder_path: "技术文档/能源管理",
            reason: "命中文件名",
          },
        ],
      },
    });

    const result = await recommendUploadFoldersApi("101", {
      files: [{ client_file_id: "local-1", file_name: "能源管理标准.pdf" }],
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/101/upload-folder-recommendations",
      { files: [{ client_file_id: "local-1", file_name: "能源管理标准.pdf" }] },
    );
    expect(result.items[0]).toMatchObject({
      clientFileId: "local-1",
      recommendedFolderId: "37",
      recommendedFolderName: "能源管理",
      recommendedFolderPath: "技术文档/能源管理",
    });
  });
});

describe("listMyUploadedFilesApi", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("maps current user uploaded file records", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: {
        data: [
          {
            id: 501,
            knowledge_id: 10,
            knowledge_name: "设备知识库",
            space_level: SpaceLevel.TEAM,
            file_name: "能源管理标准.pdf",
            file_level_path: "/37",
            folder_path_name: "能源管理",
            status: 1,
            file_encoding: "SGGF-STD-EM-20260600000001",
            tags: [{ id: 1, name: "能源" }],
            abstract: "摘要",
            create_time: "2026-06-02 10:00:00",
            update_time: "2026-06-02 10:03:00",
          },
        ],
        total: 1,
      },
    });

    const result = await listMyUploadedFilesApi({ page: 1, pageSize: 20, keyword: "能源" });

    expect(mockGet).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/my-uploaded-files",
      expect.objectContaining({
        params: expect.objectContaining({ page: 1, page_size: 20, keyword: "能源" }),
      }),
    );
    expect(result.total).toBe(1);
    expect(result.data[0]).toMatchObject({
      id: "501",
      spaceId: "10",
      spaceName: "设备知识库",
      spaceLevel: SpaceLevel.TEAM,
      name: "能源管理标准.pdf",
      folderPathName: "能源管理",
      fileEncoding: "SGGF-STD-EM-20260600000001",
    });
  });
});

describe("moveUploadedFileFolderApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("posts target folder id and maps updated file", async () => {
    mockPost.mockResolvedValue({
      status_code: 200,
      data: {
        id: 501,
        knowledge_id: 10,
        file_name: "能源管理标准.pdf",
        file_type: 1,
        file_level_path: "/37",
        status: 2,
      },
    });

    const result = await moveUploadedFileFolderApi("10", "501", "37");

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/10/files/501/move-folder",
      { target_folder_id: 37 },
    );
    expect(result.id).toBe("501");
    expect(result.path).toBe("/37");
  });
});

describe("mapChild", () => {
  it("maps summary directly when backend provides summary", () => {
    const file = mapChild(
      {
        id: 1001,
        file_name: "backend.md",
        file_type: 1,
        summary: "后端文档摘要",
      },
      "88",
    );

    expect(file).toMatchObject({
      id: "1001",
      name: "backend.md",
      type: FileType.MD,
      spaceId: "88",
      summary: "后端文档摘要",
    });
  });

  it("falls back to abstract as readonly summary", () => {
    const file = mapChild(
      {
        id: 1002,
        file_name: "database.pdf",
        file_type: 1,
        abstract: "数据库优化摘要",
      },
      "88",
    );

    expect(file.summary).toBe("数据库优化摘要");
  });
});
