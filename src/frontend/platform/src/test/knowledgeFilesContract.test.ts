import { beforeEach, expect, it, vi } from "vitest";
import * as files from "@/controllers/API/knowledgeFiles";
import {
  listChildren,
  type KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({ default: request }));
beforeEach(() => vi.resetAllMocks());

it("preserves actual folder parents including the current target and numeric ancestor fallback", async () => {
  const parents = [
    { id: 8, file_name: 8 },
    { id: 9, file_name: "Current folder" },
  ];
  request.get.mockResolvedValue(parents);
  expect(await files.listSpaceFolderParents(7, 9)).toBe(parents);
  expect(request.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/folders/9/parent",
  );
});

it.each([undefined, null, 9])(
  "projects create-folder fields without granting extra body fields: parent %s",
  async (parent_id) => {
    const body = {
      name: "  Original name  ",
      parent_id,
      tenant_id: 202,
      auth_type: "public",
      model: "19",
    };
    const folder = {
      id: 10,
      knowledge_id: 7,
      file_name: body.name,
      file_type: 0,
    };
    request.post.mockResolvedValue(folder);
    expect(await files.createSpaceFolder(7, body)).toBe(folder);
    expect(request.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/knowledge/space/7/folders",
      {
        name: body.name,
        ...(parent_id === undefined ? {} : { parent_id }),
      },
    );
  },
);

it.each(["folder", "file"] as const)(
  "renames only the requested %s using its original name body",
  async (kind) => {
    const rename =
      kind === "folder" ? files.renameSpaceFolder : files.renameSpaceFile;
    const body = { name: "New name.pdf", file_id: 99, edit: true, model: "19" };
    const response = { id: 9, knowledge_id: 7, file_name: body.name };
    request.put.mockResolvedValue(response);
    expect(await rename(7, 9, body)).toBe(response);
    expect(request.put).toHaveBeenCalledExactlyOnceWith(
      `/api/v1/knowledge/space/7/${kind}s/9`,
      { name: body.name },
    );
  },
);

it("reads original preview without requesting download, file-share, or Chunk content", async () => {
  const preview: files.SpaceFilePreview = {
    original_url: "https://objects.test/original",
    preview_url: "https://objects.test/preview",
    file_source: "web_link",
    source_url: "https://source.test",
    final_url: "https://final.test",
    web_title: "Original title",
    media_kind: "",
    html_preview_url: "https://objects.test/html",
  };
  request.get.mockResolvedValue(preview);
  expect(await files.getSpaceFilePreview(7, 9)).toBe(preview);
  expect(request.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/files/9/preview",
  );
  expect(request.post).not.toHaveBeenCalled();
});

it("keeps download as a separate original endpoint and does not synthesize preview metadata", async () => {
  const download: files.SpaceFileUrls = {
    original_url: "",
    preview_url: "https://objects.test/old",
  };
  request.get.mockResolvedValue(download);
  expect(await files.getSpaceFileDownload(7, 9)).toBe(download);
  expect(request.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/files/9/download",
  );
  expect(download).not.toHaveProperty("file_source");
});

it("uses the real search page and closed query fields with repeated array keys", async () => {
  const query = {
    keyword: "policy%_/",
    parent_id: 9,
    tag_ids: [11, 12],
    file_status: [3, 6],
    page: 2,
    page_size: 20,
    order_field: "update_time" as const,
    order_sort: "desc" as const,
    name: "wrong",
    cursor: "not-a-search-cursor",
    tenant_id: 202,
  };
  const page: files.SpaceSearchPage = {
    data: [],
    page: 2,
    page_size: 20,
    has_more: true,
  };
  request.get.mockResolvedValue(page);
  expect(await files.searchSpaceChildren(7, query)).toBe(page);
  const expected = {
    keyword: query.keyword,
    parent_id: 9,
    tag_ids: [11, 12],
    file_status: [3, 6],
    page: 2,
    page_size: 20,
    order_field: "update_time",
    order_sort: "desc",
  };
  expect(request.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/search",
    { params: expected, paramsSerializer: { indexes: null } },
  );
  const actual = await vi.importActual<typeof import("@/controllers/request")>(
    "@/controllers/request",
  );
  const wire = new URL(
    actual.default.getUri({
      url: "/api/v1/knowledge/space/7/search",
      params: expected,
      paramsSerializer: { indexes: null },
    }),
    "https://platform.test",
  );
  expect(wire.searchParams.getAll("tag_ids")).toEqual(["11", "12"]);
  expect(wire.searchParams.getAll("file_status")).toEqual(["3", "6"]);
  expect(wire.searchParams.has("tag_ids[]")).toBe(false);
  expect(wire.searchParams.get("keyword")).toBe(query.keyword);
  expect(wire.searchParams.has("name")).toBe(false);
  expect(wire.searchParams.has("cursor")).toBe(false);
  expect(page).not.toHaveProperty("total");
  expect(page).not.toHaveProperty("next_cursor");
});

it("omits absent optional search fields without replacing empty or null facts", async () => {
  request.get.mockResolvedValue({
    data: [],
    page: 1,
    page_size: 40,
    has_more: false,
  });
  await files.searchSpaceChildren(7, { page: 1, page_size: 40 });
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/7/search",
    { params: { page: 1, page_size: 40 }, paramsSerializer: { indexes: null } },
  );
  await files.searchSpaceChildren(7, {
    page: 1,
    page_size: 40,
    keyword: "",
    parent_id: null,
    tag_ids: [],
    file_status: [],
  });
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/7/search",
    {
      params: {
        page: 1,
        page_size: 40,
        keyword: "",
        parent_id: null,
        tag_ids: [],
        file_status: [],
      },
      paramsSerializer: { indexes: null },
    },
  );
});

const calls = () => [
  () => files.listSpaceFolderParents(7, 9),
  () => files.createSpaceFolder(7, { name: "Folder" }),
  () => files.renameSpaceFolder(7, 9, { name: "Folder" }),
  () => files.renameSpaceFile(7, 9, { name: "file.pdf" }),
  () => files.getSpaceFilePreview(7, 9),
  () => files.getSpaceFileDownload(7, 9),
  () => files.searchSpaceChildren(7, { page: 1, page_size: 40 }),
];

it.each([
  0,
  -1,
  1.5,
  Number.NaN,
  Number.POSITIVE_INFINITY,
  Number.MAX_SAFE_INTEGER + 1,
])(
  "rejects invalid safe-positive path or parent/tag IDs before HTTP: %s",
  async (id) => {
    const invalid = [
      () => files.listSpaceFolderParents(id, 9),
      () => files.listSpaceFolderParents(7, id),
      () => files.createSpaceFolder(id, { name: "folder" }),
      () => files.createSpaceFolder(7, { name: "folder", parent_id: id }),
      () => files.renameSpaceFolder(id, 9, { name: "folder" }),
      () => files.renameSpaceFolder(7, id, { name: "folder" }),
      () => files.renameSpaceFile(id, 9, { name: "file.pdf" }),
      () => files.renameSpaceFile(7, id, { name: "file.pdf" }),
      () => files.getSpaceFilePreview(id, 9),
      () => files.getSpaceFilePreview(7, id),
      () => files.getSpaceFileDownload(id, 9),
      () => files.getSpaceFileDownload(7, id),
      () => files.searchSpaceChildren(id, { page: 1, page_size: 40 }),
      () =>
        files.searchSpaceChildren(7, { page: 1, page_size: 40, parent_id: id }),
      () =>
        files.searchSpaceChildren(7, {
          page: 1,
          page_size: 40,
          tag_ids: [11, id],
        }),
    ];
    for (const call of invalid)
      await expect(call()).rejects.toBeInstanceOf(RangeError);
    expect(request.get).not.toHaveBeenCalled();
    expect(request.put).not.toHaveBeenCalled();
    expect(request.post).not.toHaveBeenCalled();
  },
);

it("preserves the same rejected ApiError from every endpoint", async () => {
  const error = {
    status_code: 19000,
    status_message: "original",
    data: { reference: "opaque" },
    handled: true,
  };
  request.get.mockRejectedValue(error);
  request.put.mockRejectedValue(error);
  request.post.mockRejectedValue(error);
  for (const call of calls()) await expect(call()).rejects.toBe(error);
});

it("retains actual child tags and directory flags without synthetic defaults", async () => {
  const child: KnowledgeSpaceChild = {
    id: 9,
    knowledge_id: 7,
    file_name: "Folder",
    tags: [{ id: 11, name: "Label" }],
    has_failed_files: true,
    has_abnormal_files: false,
    has_processing_files: true,
  };
  const page = {
    data: [child],
    page_size: 40,
    has_more: false,
    next_cursor: null,
  };
  request.get.mockResolvedValue(page);
  expect(await listChildren(7)).toBe(page);
  expect(child.has_abnormal_files).toBe(false);
  expect(child).not.toHaveProperty("actions");
});
