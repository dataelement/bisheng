import request from "~/api/request";
import {
  listPortalFavoritesApi,
  removePortalFavoriteApi,
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

beforeEach(() => {
  jest.clearAllMocks();
});

describe("listPortalFavoritesApi", () => {
  it("calls the favorites files endpoint with default page params", async () => {
    mockGet.mockResolvedValue({ data: { data: [], total: 0, page: 1, page_size: 20 } });

    await listPortalFavoritesApi();

    expect(mockGet).toHaveBeenCalledWith(
      `/api/v1/knowledge/shougang-portal/favorites/files`,
      { params: { page: 1, page_size: 20 } },
    );
  });

  it("forwards page and pageSize params", async () => {
    mockGet.mockResolvedValue({ data: { data: [], total: 0 } });

    await listPortalFavoritesApi({ page: 3, pageSize: 50 });

    expect(mockGet).toHaveBeenCalledWith(
      `/api/v1/knowledge/shougang-portal/favorites/files`,
      { params: { page: 3, page_size: 50 } },
    );
  });

  it("maps snake_case favorite files to camelCase and coerces ids to strings", async () => {
    mockGet.mockResolvedValue({
      data: {
        data: [
          {
            favorite_file_id: 11,
            source_space_id: 22,
            source_file_id: 33,
            title: "Doc title",
            file_name: "doc.pdf",
            status: "valid",
            updated_at: "2026-06-27T00:00:00Z",
          },
          {
            favorite_file_id: 44,
            source_space_id: 55,
            source_file_id: 66,
            title: "Gone",
            file_name: "gone.pdf",
            status: "invalid",
            updated_at: "2026-06-26T00:00:00Z",
          },
        ],
        total: 2,
      },
    });

    const result = await listPortalFavoritesApi();

    expect(result.total).toBe(2);
    expect(result.data).toEqual([
      {
        favoriteFileId: "11",
        sourceSpaceId: "22",
        sourceFileId: "33",
        title: "Doc title",
        fileName: "doc.pdf",
        status: "valid",
        updatedAt: "2026-06-27T00:00:00Z",
      },
      {
        favoriteFileId: "44",
        sourceSpaceId: "55",
        sourceFileId: "66",
        title: "Gone",
        fileName: "gone.pdf",
        status: "invalid",
        updatedAt: "2026-06-26T00:00:00Z",
      },
    ]);
  });

  it("defaults missing fields and total safely", async () => {
    mockGet.mockResolvedValue({ data: {} });

    const result = await listPortalFavoritesApi();

    expect(result).toEqual({ data: [], total: 0 });
  });

  it("normalizes unknown status to valid", async () => {
    mockGet.mockResolvedValue({
      data: { data: [{ favorite_file_id: 1 }], total: 1 },
    });

    const result = await listPortalFavoritesApi();

    expect(result.data[0].status).toBe("valid");
    expect(result.data[0].favoriteFileId).toBe("1");
    expect(result.data[0].title).toBe("");
  });
});

describe("removePortalFavoriteApi", () => {
  it("posts numeric ids to the remove endpoint and returns removed flag", async () => {
    mockPost.mockResolvedValue({ data: { removed: true } });

    const result = await removePortalFavoriteApi({
      sourceSpaceId: "22",
      sourceFileId: "33",
    });

    expect(mockPost).toHaveBeenCalledWith(
      `/api/v1/knowledge/shougang-portal/favorites/remove`,
      { source_space_id: 22, source_file_id: 33 },
    );
    expect(result).toEqual({ removed: true });
  });

  it("accepts numeric ids and defaults removed to false when absent", async () => {
    mockPost.mockResolvedValue({ data: {} });

    const result = await removePortalFavoriteApi({
      sourceSpaceId: 7,
      sourceFileId: 8,
    });

    expect(mockPost).toHaveBeenCalledWith(
      `/api/v1/knowledge/shougang-portal/favorites/remove`,
      { source_space_id: 7, source_file_id: 8 },
    );
    expect(result).toEqual({ removed: false });
  });
});
