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
  getSpaceFolderStatsApi,
  listMyUploadedFilesApi,
  mapChild,
  moveUploadedFileFolderApi,
  renameFolderApi,
  recommendUploadFoldersApi,
  retryDuplicateFilesApi,
  updateFileEncoding,
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

describe("getSpaceFolderStatsApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("posts optional filters for folder statistics", async () => {
    mockPost.mockResolvedValue({
      data: {
        stats: [
          {
            folder_id: 101,
            file_num: 2,
            success_file_num: 1,
            visible_success_file_num: 1,
            processing_file_num: 1,
          },
        ],
      },
    });

    const result = await getSpaceFolderStatsApi({
      space_id: "88",
      folder_ids: ["101", "101"],
      file_status: [2, 5],
      keyword: " 制度 ",
      tag_ids: [7],
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/88/folder-stats",
      {
        folder_ids: [101],
        file_status: [2, 5],
        keyword: "制度",
        tag_ids: [7],
      },
    );
    expect(result).toEqual([
      {
        folderId: "101",
        fileNum: 2,
        successFileNum: 1,
        visibleSuccessFileNum: 1,
        processingFileNum: 1,
      },
    ]);
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

describe("retryDuplicateFilesApi", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("keeps legacy file category string payload compatible", async () => {
    mockPost.mockResolvedValue({ status_code: 200, data: null });

    await retryDuplicateFilesApi("101", [{ id: 1, file_name: "doc.pdf" }], "RPT");

    expect(mockPost).toHaveBeenCalledWith("/api/v1/knowledge/space/101/files/retry", {
      file_objs: [{ id: 1, file_name: "doc.pdf" }],
      file_category_code: "RPT",
    });
  });

  it("posts selected upload metadata for duplicate overwrite", async () => {
    mockPost.mockResolvedValue({ status_code: 200, data: null });

    await retryDuplicateFilesApi("101", [{ id: 1, file_name: "doc.pdf" }], {
      business_domain_code: "PP",
      manual_tag_ids: [2],
      manual_tag_names: ["制度"],
    });

    expect(mockPost).toHaveBeenCalledWith("/api/v1/knowledge/space/101/files/retry", {
      file_objs: [{ id: 1, file_name: "doc.pdf" }],
      business_domain_code: "PP",
      manual_tag_ids: [2],
      manual_tag_names: ["制度"],
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

describe("updateFileEncoding", () => {
  beforeEach(() => {
    mockPut.mockReset();
  });

  it("puts the new encoding and maps updated file data", async () => {
    mockPut.mockResolvedValue({
      status_code: 200,
      data: {
        id: 501,
        knowledge_id: 10,
        file_name: "能源管理标准.pdf",
        file_type: 1,
        file_encoding: "SGGF-RPT-PP-20260600000001",
      },
    });

    const result = await updateFileEncoding("10", "501", "SGGF-RPT-PP-20260600000001");

    expect(mockPut).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/10/files/501/encoding",
      { encoding: "SGGF-RPT-PP-20260600000001" },
    );
    expect(result).toMatchObject({
      id: "501",
      spaceId: "10",
      fileEncoding: "SGGF-RPT-PP-20260600000001",
    });
  });

  it("rejects backend duplicate encoding errors", async () => {
    mockPut.mockResolvedValue({
      status_code: 18025,
      status_message: "文件编码已存在",
      data: null,
    });

    await expect(updateFileEncoding("10", "501", "SGGF-RPT-PP-20260600000001"))
      .rejects.toThrow("文件编码已存在");
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

  it("prefers web link file_name stem over fetched web_title", () => {
    const file = mapChild(
      {
        id: 1003,
        file_name: "首钢官网.md",
        file_type: 1,
        file_source: "web_link",
        user_metadata: {
          web_title: "192.168.106.171:3002",
        },
      },
      "88",
    );

    expect(file.name).toBe("首钢官网");
  });
});

describe("extractReviewTagVisibilityFlag", () => {
  it("parses boolean and string flags from nested payloads", async () => {
    const { extractReviewTagVisibilityFlag } = await import("./knowledge");

    expect(extractReviewTagVisibilityFlag({ enabled: false })).toBe(false);
    expect(extractReviewTagVisibilityFlag({ enabled: "false" })).toBe(false);
    expect(extractReviewTagVisibilityFlag({ data: { review_tag_visible: true } })).toBe(true);
    expect(extractReviewTagVisibilityFlag({ config: { review_tag_visible: "0" } })).toBe(false);
    expect(extractReviewTagVisibilityFlag(null)).toBe(null);
  });
});

describe("getKnowledgeSpaceReviewTagVisibilityApi", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("returns enabled false when review-tag-visibility reports disabled", async () => {
    const { getKnowledgeSpaceReviewTagVisibilityApi } = await import("./knowledge");
    mockGet.mockResolvedValueOnce({ data: { enabled: false } });

    const result = await getKnowledgeSpaceReviewTagVisibilityApi();

    expect(result).toEqual({ enabled: false });
    expect(mockGet).toHaveBeenCalledWith("/api/v1/knowledge/space/review-tag-visibility");
  });

  it("falls back to workstation config when primary endpoint fails", async () => {
    const { getKnowledgeSpaceReviewTagVisibilityApi } = await import("./knowledge");
    mockGet
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ data: { review_tag_visible: false } });

    const result = await getKnowledgeSpaceReviewTagVisibilityApi();

    expect(result).toEqual({ enabled: false });
    expect(mockGet).toHaveBeenNthCalledWith(1, "/api/v1/knowledge/space/review-tag-visibility");
    expect(mockGet).toHaveBeenNthCalledWith(2, "/api/v1/workstation/config/knowledge_space");
  });
});
