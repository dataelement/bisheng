import { afterEach, expect, it, vi } from "vitest";
import type { MoveSpaceGroups } from "@bisheng/knowledge";
import request from "@/controllers/request";
import { createMoveDestinationServices } from "@/controllers/API/knowledgeMoveDestinations";

vi.mock("@/controllers/request", () => ({ default: { get: vi.fn() } }));
afterEach(() => vi.resetAllMocks());

it("keeps the three membership groups and includes other visible management destinations", async () => {
  const signal = new AbortController().signal;
  vi.mocked(request.get).mockImplementation(async (url) => {
    if (url.endsWith("/list"))
      return {
        data: [
          { id: 1, name: "Department" },
          { id: 2, name: "Created" },
          { id: 3, name: "Joined" },
          { id: 5, name: "Management target", actions: ["visible"] },
        ],
        has_more: false,
        next_cursor: null,
      };
    if (url.endsWith("/department"))
      return [
        { id: 1, name: "Department" },
        { id: 4, name: "Read only" },
      ];
    if (url.endsWith("/mine"))
      return [
        { id: 2, name: "Created" },
        { id: 2, name: "Created" },
        { id: 0, name: "Invalid" },
      ];
    return [{ id: 3, name: "Joined" }];
  });
  expect(await createMoveDestinationServices(101).listSpaces(signal)).toEqual({
    department: [{ id: "1", name: "Department" }],
    created: [{ id: "2", name: "Created" }],
    joined: [{ id: "3", name: "Joined" }],
    available: [{ id: "5", name: "Management target" }],
  });
  expect(request.get).toHaveBeenCalledTimes(4);
  for (const [, config] of vi.mocked(request.get).mock.calls)
    expect(config).toEqual(
      expect.objectContaining({
        headers: { "X-Management-Tenant": "101" },
        signal,
      }),
    );
});

it("enumerates management destinations beyond 200 without an uploadable-list cutoff", async () => {
  const signal = new AbortController().signal;
  vi.mocked(request.get).mockImplementation(async (url, config) => {
    if (!url.endsWith("/list")) return [];
    const params = config?.params as { cursor?: string };
    if (params.cursor)
      return {
        data: [
          { id: 250, name: "Later management target", actions: ["visible"] },
        ],
        has_more: false,
        next_cursor: null,
      };
    return {
      data: Array.from({ length: 200 }, (_, i) => ({
        id: i + 1,
        name: `Target ${i + 1}`,
      })),
      has_more: true,
      next_cursor: "later-spaces",
    };
  });
  const groups = await createMoveDestinationServices(101).listSpaces(signal);
  expect(groups.available).toHaveLength(201);
  expect(groups.available).toContainEqual({
    id: "250",
    name: "Later management target",
  });
  expect(request.get).toHaveBeenCalledWith("/api/v1/knowledge/space/list", {
    headers: { "X-Management-Tenant": "101" },
    signal,
    params: { page_size: 200, cursor: "later-spaces" },
  });
  expect(
    vi
      .mocked(request.get)
      .mock.calls.some(([url]) => url.endsWith("/uploadable")),
  ).toBe(false);
});

it("shows the first space page before later pages and membership lists finish", async () => {
  const signal = new AbortController().signal;
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.mocked(request.get).mockImplementation(async (url, config) => {
    if (url.endsWith("/list")) {
      const cursor = (config?.params as { cursor?: string } | undefined)?.cursor;
      if (!cursor)
        return {
          data: [{ id: 5, name: "First" }],
          has_more: true,
          next_cursor: "next",
        };
      await gate;
      return {
        data: [{ id: 6, name: "Second" }],
        has_more: false,
        next_cursor: null,
      };
    }
    await gate;
    if (url.endsWith("/department")) return [{ id: 5, name: "First" }];
    return [];
  });
  const seen: MoveSpaceGroups[] = [];
  const pending = createMoveDestinationServices(101).listSpaces(signal, {
    onPartial: (groups) => seen.push(groups),
  });
  await vi.waitFor(() => expect(seen.length).toBeGreaterThan(0));
  expect(seen[0]?.available).toEqual([{ id: "5", name: "First" }]);
  release();
  await expect(pending).resolves.toEqual({
    department: [{ id: "5", name: "First" }],
    created: [],
    joined: [],
    available: [{ id: "6", name: "Second" }],
  });
});

it("sends a typed space name to the list instead of downloading every space", async () => {
  const signal = new AbortController().signal;
  vi.mocked(request.get).mockImplementation(async (url) => {
    if (url.endsWith("/list"))
      return {
        data: [{ id: 8, name: "New space" }],
        has_more: false,
        next_cursor: null,
      };
    return [];
  });
  await expect(
    createMoveDestinationServices(101).searchSpaces?.("New space", signal),
  ).resolves.toEqual({
    department: [],
    created: [],
    joined: [],
    available: [{ id: "8", name: "New space" }],
  });
  expect(request.get).toHaveBeenCalledWith("/api/v1/knowledge/space/list", {
    headers: { "X-Management-Tenant": "101" },
    signal,
    params: { page_size: 200, cursor: undefined, keyword: "New space" },
  });
});

it("loads all directory pages and preserves overlapping file and folder IDs", async () => {
  const signal = new AbortController().signal;
  vi.mocked(request.get)
    .mockResolvedValueOnce({
      data: [
        { id: 7, file_type: 0, file_name: "Folder" },
        { id: 7, file_type: 1, file_name: "File.pdf" },
      ],
      has_more: true,
      next_cursor: "page-2",
    })
    .mockResolvedValueOnce({
      data: [{ id: 8, file_type: 1, file_name: "Page 2.txt" }],
      has_more: false,
      next_cursor: null,
    });
  expect(
    await createMoveDestinationServices(101).listChildren("1", "5", signal),
  ).toEqual([
    { id: "7", name: "Folder", type: "folder" },
    { id: "7", name: "File.pdf", type: "file" },
    { id: "8", name: "Page 2.txt", type: "file" },
  ]);
  expect(request.get).toHaveBeenLastCalledWith(
    "/api/v1/knowledge/space/1/children",
    {
      headers: { "X-Management-Tenant": "101" },
      signal,
      params: {
        parent_id: "5",
        file_type: undefined,
        page_size: 200,
        order_field: "file_name",
        order_sort: "asc",
        cursor: "page-2",
      },
    },
  );
});

it("loads the folder-only tree without status filters and rejects a repeating cursor", async () => {
  const signal = new AbortController().signal;
  vi.mocked(request.get).mockResolvedValue({
    data: [{ id: 1, file_type: 0, file_name: "Folder" }],
    has_more: true,
    next_cursor: "stuck",
  });
  await expect(
    createMoveDestinationServices(101).listFolders("1", null, signal),
  ).rejects.toThrow("cursor did not progress");
  expect(request.get).toHaveBeenCalledTimes(2);
  expect(request.get).toHaveBeenCalledWith(
    "/api/v1/knowledge/space/1/children",
    expect.objectContaining({
      signal,
      params: expect.objectContaining({ parent_id: undefined, file_type: 0 }),
    }),
  );
});

it("stops loading before another page when the dialog or identity is retired", async () => {
  const controller = new AbortController();
  vi.mocked(request.get).mockImplementationOnce(async () => {
    controller.abort();
    return { data: [], has_more: true, next_cursor: "next" };
  });
  await expect(
    createMoveDestinationServices(101).listChildren(
      "1",
      null,
      controller.signal,
    ),
  ).rejects.toThrow();
  expect(request.get).toHaveBeenCalledOnce();
});
