/** @jest-environment node */

import request from "./request";
import {
  authorizeResource,
  getCreationGrantableRelationModels,
  getCreationGrantSubjects,
} from "./permission";
import { createSpaceApi } from "./knowledge";
import { createManagerChannelApi } from "./channels";

jest.mock("./request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("unified permission entry API contract", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("queries creation subjects through the tenant-scoped permission endpoint", async () => {
    mockedRequest.get.mockResolvedValueOnce({
      status_code: 200,
      data: [{ user_id: 7, user_name: "Ada" }],
    });

    await expect(getCreationGrantSubjects({
      resourceType: "knowledge_space",
      subjectType: "user",
      operation: "list",
      keyword: "Ada",
      page: 2,
      pageSize: 50,
    })).resolves.toEqual([{ user_id: 7, user_name: "Ada" }]);

    expect(mockedRequest.get).toHaveBeenCalledWith(
      "/api/v1/permissions/creation-grant-subjects",
      expect.objectContaining({
        params: {
          resource_type: "knowledge_space",
          subject_type: "user",
          operation: "list",
          keyword: "Ada",
          page: 2,
          page_size: 50,
        },
        skip403Redirect: true,
      }),
    );
  });

  it("preserves department search/path-tree response shapes", async () => {
    const tree = {
      roots: [{
        id: 8,
        dept_id: "8",
        name: "Platform",
        parent_id: null,
        path: "/8/",
      }],
      total_matches: 1,
      truncated: false,
    };
    mockedRequest.get.mockResolvedValueOnce({ status_code: 200, data: tree });

    await expect(getCreationGrantSubjects({
      resourceType: "channel",
      subjectType: "department",
      operation: "path_tree",
      departmentId: 8,
    })).resolves.toEqual(tree);

    expect(mockedRequest.get).toHaveBeenCalledWith(
      "/api/v1/permissions/creation-grant-subjects",
      expect.objectContaining({
        params: {
          resource_type: "channel",
          subject_type: "department",
          operation: "path_tree",
          department_id: 8,
        },
      }),
    );
  });

  it("reuses relation-models/grantable with creation=true and no object id", async () => {
    mockedRequest.get.mockResolvedValueOnce({
      status_code: 200,
      data: [{
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: ["view_space"],
        is_system: true,
      }],
    });

    await expect(getCreationGrantableRelationModels("knowledge_space"))
      .resolves.toHaveLength(1);
    expect(mockedRequest.get).toHaveBeenCalledWith(
      "/api/v1/permissions/relation-models/grantable",
      expect.objectContaining({
        params: { object_type: "knowledge_space", creation: true },
        skip403Redirect: true,
      }),
    );
  });

  it("keeps resource-id authorization on the existing edit endpoint", async () => {
    mockedRequest.post.mockResolvedValueOnce({ status_code: 200, data: null });

    await authorizeResource("knowledge_space", "space-1", [{
      subject_type: "user",
      subject_id: 7,
      relation: "viewer",
    }], []);

    expect(mockedRequest.post).toHaveBeenCalledWith(
      "/api/v1/permissions/resources/knowledge_space/space-1/authorize",
      {
        grants: [{ subject_type: "user", subject_id: 7, relation: "viewer" }],
        revokes: [],
      },
      expect.objectContaining({ skip403Redirect: true }),
    );
  });

  it("maps knowledge initial permissions and keeps a failed result with resource id", async () => {
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: {
        id: 42,
        name: "Docs",
        auth_type: "public",
        initial_permission_result: { status: "failed", error_code: 21009 },
      },
    });
    const grants = [{
      subject_type: "user" as const,
      subject_id: 7,
      relation: "editor" as const,
      model_id: "editor",
    }];

    const result = await createSpaceApi({
      name: "Docs",
      auth_type: "public",
      initialPermissions: { grants },
    });

    expect(mockedRequest.post).toHaveBeenCalledWith(
      "/api/v1/knowledge/space",
      {
        name: "Docs",
        auth_type: "public",
        initial_permissions: { grants },
      },
    );
    expect(result).toMatchObject({
      id: "42",
      initialPermissionResult: { status: "failed", errorCode: 21009 },
    });
  });

  it("maps channel initial permissions and keeps a failed result with string id", async () => {
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: {
        id: "channel-1",
        name: "News",
        initial_permission_result: { status: "failed", error_code: 21009 },
      },
    });
    const grants = [{
      subject_type: "department" as const,
      subject_id: 8,
      relation: "viewer" as const,
      include_children: true,
    }];

    const result = await createManagerChannelApi({
      name: "News",
      source_list: ["source-1"],
      visibility: "public",
      filter_rules: [],
      initialPermissions: { grants },
    });

    expect(mockedRequest.post).toHaveBeenCalledWith(
      "/api/v1/channel/manager/create",
      {
        name: "News",
        source_list: ["source-1"],
        visibility: "public",
        filter_rules: [],
        initial_permissions: { grants },
      },
      expect.objectContaining({ showError: true }),
    );
    expect(result).toMatchObject({
      id: "channel-1",
      initialPermissionResult: { status: "failed", errorCode: 21009 },
    });
  });

  it("keeps legacy create bodies unchanged when initial permissions are omitted", async () => {
    mockedRequest.post
      .mockResolvedValueOnce({ status_code: 200, data: { id: 43, name: "Legacy", auth_type: "private" } })
      .mockResolvedValueOnce({ status_code: 200, data: { id: "channel-2", name: "Legacy channel" } });

    const space = await createSpaceApi({ name: "Legacy", auth_type: "private" });
    const channel = await createManagerChannelApi({
      name: "Legacy channel",
      source_list: [],
      visibility: "private",
      filter_rules: [],
    });

    expect(mockedRequest.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge/space",
      { name: "Legacy", auth_type: "private" },
    );
    expect(mockedRequest.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/channel/manager/create",
      {
        name: "Legacy channel",
        source_list: [],
        visibility: "private",
        filter_rules: [],
      },
      expect.objectContaining({ showError: true }),
    );
    expect(space).toMatchObject({ id: "43" });
    expect(space.initialPermissionResult).toBeUndefined();
    expect(channel).toMatchObject({ id: "channel-2" });
    expect(channel.initialPermissionResult).toBeUndefined();
  });
});
