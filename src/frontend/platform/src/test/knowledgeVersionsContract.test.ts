import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  getSpaceFileVersions,
  searchVersionDocuments,
  getVersionRecommendations,
  linkSpaceFileVersion,
  mergeSpaceFileVersion,
  setSpacePrimaryVersion,
  deleteSpaceFileVersion,
  dismissSpaceSimilarFile,
  type SpaceVersionHistory,
} from "@/controllers/API/knowledgeVersions";

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({ default: request }));
beforeEach(() => vi.resetAllMocks());
afterEach(() => vi.unstubAllGlobals());

it("reads the exact existing file history endpoint with cancellation and nullable facts", async () => {
  const history: SpaceVersionHistory = {
    document_id: 41,
    knowledge_id: 7,
    title: "Visible anchor",
    doc_code: null,
    current_primary_version_no: null,
    versions: [
      {
        version_id: 51,
        version_no: 3,
        is_primary: false,
        knowledge_file_id: 11,
        original_file_name: "original.md",
        file_code: null,
        uploader_name: null,
        uploader_id: null,
        upload_time: null,
        status: null,
      },
    ],
  };
  request.get.mockResolvedValue(history);
  const signal = new AbortController().signal;
  expect(await getSpaceFileVersions(11, signal)).toBe(history);
  expect(request.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/file/11/versions",
    { signal },
  );
  expect(history.current_primary_version_no).toBeNull();
  expect(history.versions[0].file_code).toBeNull();
});

it.each([0, -1, 1.5, Number.NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
  "rejects invalid file IDs before HTTP: %s",
  async (id) => {
    await expect(getSpaceFileVersions(id)).rejects.toBeInstanceOf(RangeError);
    expect(request.get).not.toHaveBeenCalled();
  },
);

it("preserves the original ApiError object for read failures", async () => {
  const error = {
    status_code: 19000,
    status_message: "original",
    handled: true,
  };
  request.get.mockRejectedValue(error);
  await expect(getSpaceFileVersions(11)).rejects.toBe(error);
});

it("uses the wrapped request transport and leaves backend error normalization intact", async () => {
  vi.stubGlobal("localStorage", { getItem: () => null });
  const actual = await vi.importActual<typeof import("@/controllers/request")>(
    "@/controllers/request",
  );
  request.get.mockImplementation((url, config) =>
    actual.default.get(url, {
      ...config,
      adapter: async (wire) => {
        expect(wire.url).toBe("/api/v1/knowledge/space/file/11/versions");
        expect(wire.headers.get("X-Management-Tenant")).toBeUndefined();
        return {
          data: { status_code: 19000, status_message: "denied", data: null },
          status: 200,
          statusText: "OK",
          headers: {},
          config: wire,
        };
      },
    }),
  );
  await expect(getSpaceFileVersions(11)).rejects.toMatchObject({
    status_code: 19000,
  });
});

it("uses bounded original cursor endpoints and preserves opaque cursors and candidate direction", async () => {
  const signal = new AbortController().signal;
  request.get.mockResolvedValue({
    data: [],
    has_more: false,
    next_cursor: null,
    page_size: 40,
  });
  await searchVersionDocuments(7, 11, "literal %_", true, "opaque+/=", signal);
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/7/document/version-search-page",
    {
      params: {
        keyword: "literal %_",
        current_file_id: 11,
        page_size: 40,
        cursor: "opaque+/=",
      },
      signal,
    },
  );
  await searchVersionDocuments(7, 11, "", false, undefined, signal);
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/7/document/search-page",
    { params: { keyword: "", current_file_id: 11, page_size: 40 }, signal },
  );
  await getVersionRecommendations(11, true, signal);
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/file/11/version-recommendations",
    { signal },
  );
  await getVersionRecommendations(11, false, signal);
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/file/11/similar",
    { signal },
  );
});

it("keeps link, merge, primary, historical delete and dismissal on their exact original protocols", async () => {
  const signal = new AbortController().signal;
  await linkSpaceFileVersion(11, 41, signal);
  expect(request.post).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/document/link",
    { knowledge_file_id: 11, target_document_id: 41 },
    { signal },
  );
  await mergeSpaceFileVersion(11, 61, signal);
  expect(request.post).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/version/merge",
    { current_knowledge_file_id: 11, source_document_id: 61 },
    { signal },
  );
  await setSpacePrimaryVersion(51, signal);
  expect(request.post).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/version/51/set-primary",
    undefined,
    { signal },
  );
  await deleteSpaceFileVersion(51, signal);
  expect(request.delete).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/version/51",
    { signal },
  );
  await dismissSpaceSimilarFile(11, signal);
  expect(request.post).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/file/11/dismiss-similar",
    undefined,
    { signal },
  );
});

it("rejects malformed write IDs before transport and preserves unknown ACK rejection without retry", async () => {
  await expect(linkSpaceFileVersion(11, 0)).rejects.toBeInstanceOf(RangeError);
  await expect(
    mergeSpaceFileVersion(true as unknown as number, 61),
  ).rejects.toBeInstanceOf(RangeError);
  expect(request.post).not.toHaveBeenCalled();
  const error = { status_code: 500, handled: true };
  request.post.mockRejectedValue(error);
  await expect(setSpacePrimaryVersion(51)).rejects.toBe(error);
  expect(request.post).toHaveBeenCalledTimes(1);
});
