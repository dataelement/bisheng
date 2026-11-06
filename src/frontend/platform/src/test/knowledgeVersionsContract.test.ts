import { beforeEach, expect, it, vi } from "vitest";
import {
  getSpaceFileVersions,
  type SpaceVersionHistory,
} from "@/controllers/API/knowledgeVersions";

const request = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: request }));
beforeEach(() => vi.resetAllMocks());

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
