import request from "~/api/request";
import {
  authorizeChannelApi,
  canEditChannelSettings,
  canManageChannelPermissions,
  ChannelRole,
  getChannelGrantSubjectsUsersApi,
  getChannelPermissionsApi,
} from "./channels";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;
const mockPost = request.post as jest.Mock;

describe("channel permission APIs", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it("uses channel manager permissions endpoint", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: {
        data: [
          {
            subject_type: "user",
            subject_id: 2,
            subject_name: "Alice",
            relation: "viewer",
          },
        ],
      },
    });

    await expect(getChannelPermissionsApi("channel-1")).resolves.toHaveLength(1);
    expect(mockGet).toHaveBeenCalledWith(
      "/api/v1/channel/manager/channel-1/permissions",
      { skip403Redirect: true },
    );
  });

  it("uses channel manager authorize endpoint", async () => {
    mockPost.mockResolvedValue({ status_code: 200, data: null });

    await authorizeChannelApi("channel-1", {
      grants: [{ subject_type: "user", subject_id: 2, relation: "viewer" }],
      revokes: [],
    });

    expect(mockPost).toHaveBeenCalledWith(
      "/api/v1/channel/manager/channel-1/authorize",
      {
        grants: [{ subject_type: "user", subject_id: 2, relation: "viewer" }],
        revokes: [],
      },
      { skip403Redirect: true },
    );
  });

  it("uses channel manager grant subjects endpoint", async () => {
    mockGet.mockResolvedValue({
      status_code: 200,
      data: { data: [{ user_id: 2, user_name: "Alice" }] },
    });

    await expect(
      getChannelGrantSubjectsUsersApi(
        "channel-1",
        { keyword: "ali", page: 2, page_size: 50 },
        { signal: undefined },
      ),
    ).resolves.toEqual([{ user_id: 2, user_name: "Alice" }]);
    expect(mockGet).toHaveBeenCalledWith(
      "/api/v1/channel/manager/channel-1/grant-subjects/users",
      {
        params: { keyword: "ali", page: 2, page_size: 50 },
        skip403Redirect: true,
        signal: undefined,
      },
    );
  });
});

describe("channel relation helpers", () => {
  it("allows editor to edit channel settings without managing permissions", () => {
    expect(canEditChannelSettings("owner")).toBe(true);
    expect(canEditChannelSettings("manager")).toBe(true);
    expect(canEditChannelSettings("editor")).toBe(true);
    expect(canEditChannelSettings(ChannelRole.CREATOR)).toBe(true);
    expect(canEditChannelSettings(ChannelRole.ADMIN)).toBe(true);
    expect(canEditChannelSettings("viewer")).toBe(false);
    expect(canEditChannelSettings(ChannelRole.MEMBER)).toBe(false);
  });

  it("allows new owner/manager and legacy creator/admin to manage permissions", () => {
    expect(canManageChannelPermissions("owner")).toBe(true);
    expect(canManageChannelPermissions("manager")).toBe(true);
    expect(canManageChannelPermissions(ChannelRole.CREATOR)).toBe(true);
    expect(canManageChannelPermissions(ChannelRole.ADMIN)).toBe(true);
    expect(canManageChannelPermissions("editor")).toBe(false);
    expect(canManageChannelPermissions("viewer")).toBe(false);
    expect(canManageChannelPermissions(ChannelRole.MEMBER)).toBe(false);
  });
});
