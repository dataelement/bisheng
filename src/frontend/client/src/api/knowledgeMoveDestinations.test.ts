/** @jest-environment node */

import request from "~/api/request";
import { moveDestinationServices } from "~/api/knowledgeMoveDestinations";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

const get = jest.mocked(request.get);
afterEach(() => jest.resetAllMocks());

it("unwraps client response envelopes and intersects each space group with upload permission", async () => {
  const signal = new AbortController().signal;
  get.mockImplementation(async (url) => {
    if (url.endsWith("/uploadable"))
      return { status_code: 200, data: { data: [{ id: 1 }, { id: 2 }, { id: 3 }] } };
    if (url.endsWith("/department"))
      return { status_code: 200, data: [{ id: 1, name: "Department" }, { id: 4, name: "Read only" }] };
    if (url.endsWith("/mine"))
      return { status_code: 200, data: [{ id: 2, name: "Created" }, { id: 2, name: "Created" }, { id: 0, name: "Invalid" }] };
    return { status_code: 200, data: [{ id: 3, name: "Joined" }] };
  });
  expect(await moveDestinationServices.listSpaces(signal)).toEqual({
    department: [{ id: "1", name: "Department" }],
    created: [{ id: "2", name: "Created" }],
    joined: [{ id: "3", name: "Joined" }],
  });
  expect(get).toHaveBeenCalledTimes(4);
  for (const [, config] of get.mock.calls) expect(config).toEqual({ signal });
});

it("unwraps every directory page and preserves files and folders with the same ID", async () => {
  const signal = new AbortController().signal;
  get.mockResolvedValueOnce({ status_code: 200, data: {
    data: [{ id: 7, file_type: 0, file_name: "Folder" }, { id: 7, file_type: 1, file_name: "File.pdf" }],
    has_more: true, next_cursor: "page-2",
  } }).mockResolvedValueOnce({ status_code: 200, data: {
    data: [{ id: 8, file_type: 1, file_name: "Page 2.txt" }], has_more: false, next_cursor: null,
  } });
  expect(await moveDestinationServices.listChildren("1", "5", signal)).toEqual([
    { id: "7", name: "Folder", type: "folder" },
    { id: "7", name: "File.pdf", type: "file" },
    { id: "8", name: "Page 2.txt", type: "file" },
  ]);
  expect(get).toHaveBeenLastCalledWith("/api/v1/knowledge/space/1/children", {
    signal,
    params: { parent_id: "5", file_type: undefined, page_size: 200, order_field: "file_name", order_sort: "asc", cursor: "page-2" },
  });
});

it("requests folders only and omits root parent and status filters", async () => {
  const signal = new AbortController().signal;
  get.mockResolvedValueOnce({ status_code: 200, data: {
    data: [{ id: 7, file_type: 0, file_name: "Folder" }, { id: 7, file_type: 1, file_name: "File.pdf" }, { id: 0, file_type: 0, file_name: "Invalid" }],
    has_more: false, next_cursor: null,
  } });
  expect(await moveDestinationServices.listFolders("1", null, signal)).toEqual([
    { id: "7", name: "Folder", type: "folder" },
  ]);
  expect(get).toHaveBeenCalledWith("/api/v1/knowledge/space/1/children", {
    signal,
    params: { parent_id: undefined, file_type: 0, page_size: 200, order_field: "file_name", order_sort: "asc", cursor: undefined },
  });
});

it("rejects a cursor that does not progress instead of looping", async () => {
  get.mockResolvedValue({ status_code: 200, data: { data: [], has_more: true, next_cursor: "stuck" } });
  await expect(moveDestinationServices.listChildren("1", null, new AbortController().signal))
    .rejects.toThrow("cursor did not progress");
  expect(get).toHaveBeenCalledTimes(2);
});

it("stops before fetching another page when its picker session is aborted", async () => {
  const controller = new AbortController();
  get.mockImplementationOnce(async () => {
    controller.abort();
    return { status_code: 200, data: { data: [], has_more: true, next_cursor: "next" } };
  });
  await expect(moveDestinationServices.listChildren("1", null, controller.signal)).rejects.toThrow();
  expect(get).toHaveBeenCalledTimes(1);
});
