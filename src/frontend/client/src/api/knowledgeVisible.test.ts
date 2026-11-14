import request from "./request";
import {
  getVisibleSpacesPageApi,
  getVisibleSpacesTenant,
} from "./knowledgeVisible";
jest.mock("./request", () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));
const transport = jest.mocked(request.get);

test("uses the real cursor, maps direct grants and preserves an empty nonterminal page", async () => {
  transport.mockResolvedValueOnce({
    status_code: 200,
    data: {
      data: [],
      page_size: 50,
      has_more: true,
      next_cursor: "actual-next",
    },
  });
  expect(
    await getVisibleSpacesPageApi({
      keyword: " direct ",
      cursor: "actual-current",
    }),
  ).toEqual({
    data: [],
    page_size: 50,
    has_more: true,
    next_cursor: "actual-next",
  });
  expect(transport).toHaveBeenCalledWith("/api/v1/knowledge/space/list", {
    params: { keyword: "direct", cursor: "actual-current", page_size: 50 },
    signal: undefined,
  });
  transport.mockResolvedValueOnce({
    status_code: 200,
    data: {
      data: [
        {
          id: 41,
          name: "Direct grant",
          user_role: null,
          actions: ["visible"],
          state: 1,
        },
      ],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    },
  });
  expect((await getVisibleSpacesPageApi()).data[0]).toMatchObject({
    id: "41",
    name: "Direct grant",
    actions: ["visible"],
  });
});

test.each([null, "", "same"])(
  "rejects a nonadvancing cursor %s",
  async (cursor) => {
    transport.mockResolvedValueOnce({
      status_code: 200,
      data: { data: [], has_more: true, next_cursor: cursor },
    });
    await expect(getVisibleSpacesPageApi({ cursor: "same" })).rejects.toThrow(
      "Invalid visible spaces page",
    );
  },
);

test("reads actual tenant, rejects absent tenant and an oversized request", async () => {
  transport.mockResolvedValueOnce({
    status_code: 200,
    data: { leaf_tenant_id: 101 },
  });
  await expect(getVisibleSpacesTenant()).resolves.toBe(101);
  transport.mockResolvedValueOnce({ status_code: 200, data: {} });
  await expect(getVisibleSpacesTenant()).rejects.toThrow(
    "Invalid current tenant",
  );
  await expect(getVisibleSpacesPageApi({ page_size: 201 })).rejects.toThrow(
    "Invalid page size",
  );
});
