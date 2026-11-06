import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as uploads from "@/controllers/API/knowledgeUploads";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";

const request = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: request }));
beforeEach(() => vi.resetAllMocks());
afterEach(() => vi.unstubAllGlobals());

it("stages the actual multipart file without an invented body or management header", async () => {
  const file = new File(["content"], "original.md", { type: "text/markdown" });
  const signal = new AbortController().signal;
  const result: uploads.SpaceUploadFile = {
    file_path: "tmp/original.md",
    relative_path: "tmp/original.md",
    file_name: file.name,
    repeat: true,
    repeat_file_name: "existing.md",
    repeat_update_time: "2026-11-07T12:00:00",
    cover_filepath: null,
  };
  request.post.mockResolvedValue(result);
  expect(await uploads.uploadSpaceFile(7, file, signal)).toBe(result);
  const [url, body, options] = request.post.mock.calls[0];
  expect(url).toBe("/api/v1/knowledge/upload/7");
  expect(body).toBeInstanceOf(FormData);
  expect([...body.keys()]).toEqual(["file"]);
  expect(body.get("file")).toBe(file);
  expect(options).toEqual({ signal });
});

it.each([undefined, null, 9])(
  "registers inherited rules without manufacturing defaults: parent %s",
  async (parent_id) => {
    const response: KnowledgeSpaceChild[] = [
      {
        id: 92,
        knowledge_id: 7,
        file_name: "duplicate.md",
        status: 3,
        remark: "original failure",
      },
      { id: 81, knowledge_id: 7, file_name: "accepted.md", status: 5 },
    ];
    const body = {
      file_path: ["tmp/a", "tmp/b"],
      parent_id,
      tenant_id: 202,
      model: 19,
      excel_rule: {},
    };
    request.post.mockResolvedValue(response);
    expect(await uploads.registerSpaceFiles(7, body)).toBe(response);
    expect(request.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/knowledge/space/7/files",
      {
        file_path: body.file_path,
        ...(parent_id === undefined ? {} : { parent_id }),
      },
      { signal: undefined },
    );
    expect(request.post.mock.calls[0][1]).not.toHaveProperty("overrides");
  },
);

it.each([
  null,
  {},
  {
    document: { chunk_overlap: 0, append_title: false, separator: ["", "\\n"] },
    table: { append_header: 0 as const },
  },
])(
  "preserves the real typed optional batch overrides %j",
  async (overrides) => {
    const signal = new AbortController().signal;
    request.post.mockResolvedValue([]);
    await uploads.registerSpaceFiles(
      7,
      { file_path: ["tmp/a"], overrides },
      signal,
    );
    expect(request.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/knowledge/space/7/files",
      {
        file_path: ["tmp/a"],
        overrides,
      },
      { signal },
    );
  },
);

it.each([
  0,
  -1,
  1.5,
  Number.NaN,
  Number.POSITIVE_INFINITY,
  Number.MAX_SAFE_INTEGER + 1,
])("rejects unsafe path and parent IDs before HTTP: %s", async (id) => {
  await expect(
    uploads.uploadSpaceFile(id, new File(["a"], "a.txt")),
  ).rejects.toBeInstanceOf(RangeError);
  await expect(
    uploads.registerSpaceFiles(id, { file_path: ["tmp/a"] }),
  ).rejects.toBeInstanceOf(RangeError);
  await expect(
    uploads.registerSpaceFiles(7, { file_path: ["tmp/a"], parent_id: id }),
  ).rejects.toBeInstanceOf(RangeError);
  expect(request.post).not.toHaveBeenCalled();
});

it.each(["stage", "register"])(
  "keeps the exact rejected ApiError for %s",
  async (operation) => {
    const error = {
      status_code: 10999,
      status_message: "original",
      data: { reason: "processing" },
    };
    request.post.mockRejectedValue(error);
    const promise =
      operation === "stage"
        ? uploads.uploadSpaceFile(7, new File(["a"], "a.txt"))
        : uploads.registerSpaceFiles(7, { file_path: ["tmp/a"] });
    await expect(promise).rejects.toBe(error);
  },
);

it("uses the real wrapped request's conditional staging pin and no registration management header", async () => {
  vi.stubGlobal("localStorage", { getItem: () => null });
  const actual = await vi.importActual<typeof import("@/controllers/request")>(
    "@/controllers/request",
  );
  const management = await import("@/controllers/managementScope");
  const observed: {
    url?: string;
    pin: unknown;
    data: unknown;
    signal: unknown;
  }[] = [];
  const originalAdapter = actual.default.defaults.adapter;
  actual.default.defaults.adapter = async (config) => {
    observed.push({
      url: config.url,
      pin: config.headers.get("X-Management-Tenant"),
      data: config.data,
      signal: config.signal,
    });
    return {
      status: 200,
      statusText: "OK",
      config,
      headers: {},
      data: { status_code: 200, status_message: "success", data: [] },
    };
  };
  management.acceptManagementScope(101);
  request.post.mockImplementation(
    (...args: Parameters<typeof actual.default.post>) =>
      actual.default.post(...args),
  );
  const signal = new AbortController().signal;
  try {
    await uploads.uploadSpaceFile(7, new File(["a"], "a.txt"), signal);
    await uploads.registerSpaceFiles(7, { file_path: ["tmp/a"] }, signal);
    expect(observed.map(({ url, pin }) => ({ url, pin }))).toEqual([
      { url: "/api/v1/knowledge/upload/7", pin: "101" },
      { url: "/api/v1/knowledge/space/7/files", pin: undefined },
    ]);
    expect(observed[0].data).toBeInstanceOf(FormData);
    expect(observed[0].signal).toBe(signal);
    expect(JSON.parse(String(observed[1].data))).toEqual({
      file_path: ["tmp/a"],
    });
  } finally {
    management.acceptManagementScope(null);
    actual.default.defaults.adapter = originalAdapter;
  }
});
