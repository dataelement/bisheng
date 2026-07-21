import request from "~/api/request";
import {
  FileType,
  SpaceLevel,
  VisibilityType,
  batchDeleteApi,
  batchDownloadApi,
  createFolderApi,
  deleteFolderApi,
  deleteSpaceApi,
  downloadWatermarkedKnowledgeFileApi,
  getSpaceInfoApi,
  getSquareSpacesApi,
  getSpaceFolderStatsApi,
  listMyUploadedFilesApi,
  mapChild,
  mapSpace,
  moveUploadedFileFolderApi,
  renameFolderApi,
  recommendUploadFoldersApi,
  retryDuplicateFilesApi,
  updateFileEncoding,
  updateSpaceApi,
} from "./knowledge";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    getResponse: jest.fn(),
    post: jest.fn(),
    postMultiPart: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;
const mockGetResponse = request.getResponse as jest.Mock;
const mockPost = request.post as jest.Mock;
const mockPostMultiPart = request.postMultiPart as jest.Mock;
const mockPut = request.put as jest.Mock;
const mockDelete = request.delete as jest.Mock;

describe("getSpaceInfoApi", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("keeps omitted statistics undefined for detail responses", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: {
        id: 200,
        name: "目标知识库",
        auth_type: VisibilityType.PRIVATE,
        user_name: "创建人",
        user_id: 1,
        user_role: "member",
        space_level: SpaceLevel.TEAM,
      },
    });

    const result = await getSpaceInfoApi("200");

    expect(mockGet).toHaveBeenCalledWith("/api/v1/knowledge/space/200/info");
    expect(result).toMatchObject({
      id: "200",
      name: "目标知识库",
      creator: "创建人",
      spaceLevel: SpaceLevel.TEAM,
    });
    expect(result.memberCount).toBeUndefined();
    expect(result.fileCount).toBeUndefined();
    expect(result.totalFileCount).toBeUndefined();
  });
});

describe("updateSpaceApi", () => {
  beforeEach(() => {
    mockPut.mockReset();
  });

  it("forwards department_id without adding space_level", async () => {
    mockPut.mockResolvedValue({
      status_code: 200,
      data: {
        id: 200,
        name: "部门知识库",
        auth_type: VisibilityType.PRIVATE,
        space_level: SpaceLevel.DEPARTMENT,
        department_id: 12,
      },
    });

    await updateSpaceApi("200", { department_id: 12 });

    expect(mockPut).toHaveBeenCalledWith("/api/v1/knowledge/space/200", {
      department_id: 12,
    });
    expect(mockPut.mock.calls[0][1]).not.toHaveProperty("space_level");
  });
});

describe("mapSpace", () => {
  it("preserves list statistics when the response provides them", () => {
    const result = mapSpace({
      id: 201,
      name: "列表知识库",
      auth_type: VisibilityType.PUBLIC,
      follower_num: 2,
      file_num: 3,
    } as any);

    expect(result.memberCount).toBe(2);
    expect(result.fileCount).toBe(3);
    expect(result.totalFileCount).toBe(3);
  });
});

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

describe("deleteSpaceApi", () => {
  beforeEach(() => {
    mockDelete.mockReset();
  });

  // A blocked delete (e.g. 权限不足 / 自由库迁移条件不满足) comes back as HTTP 200 with an
  // envelope status_code !== 200. Passing skip403Redirect opts the call into the response
  // interceptor's business-error pipeline, which toasts the backend message and rejects —
  // so the caller shows the reason instead of a false "删除成功".
  it("opts into the business-error pipeline via skip403Redirect", async () => {
    mockDelete.mockResolvedValue({ status_code: 200, data: null });

    await deleteSpaceApi("175");

    expect(mockDelete).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/175",
      { skip403Redirect: true },
    );
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

describe("downloadWatermarkedKnowledgeFileApi", () => {
  const createObjectURL = jest.fn(() => "blob:watermarked-pdf");
  const revokeObjectURL = jest.fn();
  let clickSpy: jest.SpyInstance;

  beforeEach(() => {
    mockGetResponse.mockReset();
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    clickSpy = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  afterEach(() => {
    clickSpy.mockRestore();
  });

  it("downloads the binary PDF with its RFC 5987 filename and entry point", async () => {
    mockGetResponse.mockResolvedValue({
      data: new Blob(["%PDF-1.7"], { type: "application/pdf" }),
      headers: {
        "content-disposition": "attachment; filename=\"document.pdf\"; filename*=UTF-8''%E8%AE%BE%E5%A4%87%E6%A3%80%E4%BF%AE.pdf",
        "content-type": "application/pdf",
      },
      status: 200,
    });

    await downloadWatermarkedKnowledgeFileApi({
      spaceId: "12",
      fileId: "1580",
      entryPoint: "bisheng_knowledge_list",
      fallbackFileName: "设备检修.docx",
    });

    expect(mockGetResponse).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/12/files/1580/download",
      {
        params: { entry_point: "bisheng_knowledge_list" },
        responseType: "blob",
      },
    );
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:watermarked-pdf");
  });

  it("falls back to a sanitized PDF filename", async () => {
    mockGetResponse.mockResolvedValue({
      data: new Blob(["%PDF-1.7"], { type: "application/pdf" }),
      headers: { "content-type": "application/pdf" },
      status: 200,
    });
    const createdAnchors: HTMLAnchorElement[] = [];
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = jest.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === "a") createdAnchors.push(element as HTMLAnchorElement);
      return element;
    }) as typeof document.createElement);

    try {
      await downloadWatermarkedKnowledgeFileApi({
        spaceId: "12",
        fileId: "1580",
        entryPoint: "bisheng_preview",
        fallbackFileName: "../检修\n方案.docx",
      });
    } finally {
      createElementSpy.mockRestore();
    }

    expect(createdAnchors[0].download).toBe("检修方案.pdf");
  });

  it("parses JSON blob errors without starting a browser download", async () => {
    mockGetResponse.mockRejectedValue({
      response: {
        status: 409,
        data: new Blob([
          JSON.stringify({ status_code: 18085, status_message: "PDF 生成失败，请稍后重试" }),
        ], { type: "application/json" }),
      },
    });

    await expect(downloadWatermarkedKnowledgeFileApi({
      spaceId: "12",
      fileId: "1580",
      entryPoint: "bisheng_version_history",
      fallbackFileName: "历史版本.docx",
    })).rejects.toThrow("PDF 生成失败，请稍后重试");
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });

  it("shows a stable message when on-demand PDF generation times out", async () => {
    mockGetResponse.mockRejectedValue({
      response: {
        status: 504,
        data: new Blob(["gateway timeout"], { type: "text/plain" }),
      },
    });

    await expect(downloadWatermarkedKnowledgeFileApi({
      spaceId: "12",
      fileId: "1580",
      entryPoint: "bisheng_knowledge_list",
      fallbackFileName: "设备检修.docx",
    })).rejects.toThrow("PDF 生成超时，请稍后重试");
    expect(createObjectURL).not.toHaveBeenCalled();
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

describe("resolveSpaceTagAddHint", () => {
  it("returns under_review for pending review tags", async () => {
    const { resolveSpaceTagAddHint } = await import("./knowledge");
    expect(resolveSpaceTagAddHint({ id: 1, name: "待审核", review_status: 0 })).toBe("under_review");
  });

  it("returns exists_in_other_library for unbound library tags", async () => {
    const { resolveSpaceTagAddHint } = await import("./knowledge");
    expect(
      resolveSpaceTagAddHint(
        { id: 2, name: "全局标签", business_type: "tag_library", resource_type: "system_tag" },
        [{ name: "系统A" }],
      ),
    ).toBe("exists_in_other_library");
  });

  it("returns null for bound library tags", async () => {
    const { resolveSpaceTagAddHint } = await import("./knowledge");
    expect(
      resolveSpaceTagAddHint(
        { id: 3, name: "系统A", business_type: "tag_library", resource_type: "system_tag" },
        [{ name: "系统A" }],
      ),
    ).toBeNull();
  });
});

describe("isPendingReviewTagStatus", () => {
  it("detects pending review tags", async () => {
    const { isPendingReviewTagStatus } = await import("./knowledge");
    expect(isPendingReviewTagStatus(0)).toBe(true);
    expect(isPendingReviewTagStatus(1)).toBe(false);
    expect(isPendingReviewTagStatus(undefined)).toBe(false);
  });
});

describe("extractTagLibraryPreviewNames", () => {
  it("includes ai_auto_tag names from tag_items", async () => {
    const { extractTagLibraryPreviewNames } = await import("./knowledge");
    expect(
      extractTagLibraryPreviewNames({
        tags: ["手动标签"],
        tag_items: [
          { name: "手动标签", resource_type: "manual_tag" },
          { name: "AI标签", resource_type: "ai_auto_tag" },
        ],
      }),
    ).toEqual(["手动标签", "AI标签"]);
  });

  it("falls back to tags when tag_items is empty", async () => {
    const { extractTagLibraryPreviewNames } = await import("./knowledge");
    expect(
      extractTagLibraryPreviewNames({
        tags: ["系统A", "系统B"],
        tag_items: [],
      }),
    ).toEqual(["系统A", "系统B"]);
  });
});
