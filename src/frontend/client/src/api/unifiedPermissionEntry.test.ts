/** @jest-environment node */

import request, { translateApiErrorMessage } from "./request";
import {
  authorizeResource,
  getResourcePermissions,
  getCreationGrantableRelationModels,
  getCreationGrantSubjects,
  getFailedAuthorizationGrants,
} from "./permission";
import { createSpaceApi } from "./knowledge";
import {
  authorizeChannelApi,
  createManagerChannelApi,
  getChannelPermissionsApi,
} from "./channels";

jest.mock("./request", () => ({
  ...jest.requireActual("./request"),
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockedRequest = request as jest.Mocked<typeof request>;
const PERSONAL_INVITE_SCENARIO_DISABLED_MESSAGE = String.fromCodePoint(
  0x4e2a, 0x4eba, 0x7528, 0x6237, 0x9080, 0x8bf7, 0x786e, 0x8ba4,
  0x573a, 0x666f, 0x672a, 0x542f, 0x7528, 0xff0c, 0x65e0, 0x6cd5,
  0x65b0, 0x589e, 0x4e2a, 0x4eba, 0x7528, 0x6237, 0x6743, 0x9650,
);

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
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: {
        direct_applied_count: 1,
        invite_created_count: 1,
        invite_existing_count: 0,
        failed_count: 0,
        results: [{
          operation: "grant",
          subject_type: "user",
          subject_id: 7,
          relation: "viewer",
          model_id: "viewer",
          outcome: "invite_created",
          approval_instance_id: 1201,
        }],
      },
    });

    const result = await authorizeResource("knowledge_space", "space-1", [{
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
    expect(result).toMatchObject({
      directAppliedCount: 1,
      inviteCreatedCount: 1,
      inviteExistingCount: 0,
      failedCount: 0,
      results: [{
        subjectType: "user",
        subjectId: 7,
        outcome: "invite_created",
        approvalInstanceId: 1201,
      }],
    });
  });

  it("maps channel authorization and preserves legacy channel counters", async () => {
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: {
        synced_user_count: 2,
        affected_member_count: 3,
        invite_existing_count: 1,
        results: [{
          operation: "grant",
          subject_type: "user",
          subject_id: 8,
          relation: "editor",
          outcome: "invite_existing",
        }],
      },
    });

    await expect(authorizeChannelApi("channel-1", {
      grants: [{ subject_type: "user", subject_id: 8, relation: "editor" }],
      revokes: [],
    })).resolves.toMatchObject({
      syncedUserCount: 2,
      affectedMemberCount: 3,
      inviteExistingCount: 1,
      results: [{ subjectId: 8, outcome: "invite_existing" }],
    });
  });

  it("maps pending permission fields and defaults old rows to active", async () => {
    mockedRequest.get
      .mockResolvedValueOnce({
        status_code: 200,
        data: [{
          subject_type: "user",
          subject_id: 7,
          subject_name: "Ada",
          relation: "viewer",
          authorization_status: "pending",
          approval_instance_id: 1201,
        }],
      })
      .mockResolvedValueOnce({
        status_code: 200,
        data: [{
          subject_type: "department",
          subject_id: 8,
          subject_name: "Platform",
          relation: "viewer",
        }],
      });

    await expect(getResourcePermissions("knowledge_space", "space-1"))
      .resolves.toEqual([expect.objectContaining({
        authorizationStatus: "pending",
        approvalInstanceId: 1201,
      })]);
    await expect(getChannelPermissionsApi("channel-1"))
      .resolves.toEqual([expect.objectContaining({
        authorizationStatus: "active",
        approvalInstanceId: null,
      })]);
  });

  it("keeps the explicit 18106 status message", async () => {
    expect(translateApiErrorMessage({
      status_code: 18106,
      status_message: PERSONAL_INVITE_SCENARIO_DISABLED_MESSAGE,
    })).toBe(PERSONAL_INVITE_SCENARIO_DISABLED_MESSAGE);

    mockedRequest.post.mockResolvedValueOnce({
      status_code: 18106,
      status_message: PERSONAL_INVITE_SCENARIO_DISABLED_MESSAGE,
      data: { exception: PERSONAL_INVITE_SCENARIO_DISABLED_MESSAGE },
    });

    await expect(authorizeResource("knowledge_space", "space-1", [{
      subject_type: "user",
      subject_id: 7,
      relation: "viewer",
    }], [])).rejects.toThrow(PERSONAL_INVITE_SCENARIO_DISABLED_MESSAGE);
  });

  it("defaults missing authorization result fields for old responses", async () => {
    mockedRequest.post.mockResolvedValueOnce({ status_code: 200, data: null });

    await expect(authorizeResource("knowledge_space", "space-1", [], []))
      .resolves.toEqual({
        syncedUserCount: 0,
        affectedMemberCount: 0,
        directAppliedCount: 0,
        inviteCreatedCount: 0,
        inviteExistingCount: 0,
        failedCount: 0,
        results: [],
      });
  });

  it("selects only failed grants for create recovery", () => {
    const grants = [
      { subject_type: "department" as const, subject_id: 8, relation: "viewer" as const },
      { subject_type: "user" as const, subject_id: 7, relation: "editor" as const, model_id: "editor" },
    ];

    expect(getFailedAuthorizationGrants(grants, [
      {
        operation: "grant",
        subjectType: "department",
        subjectId: 8,
        relation: "viewer",
        modelId: null,
        outcome: "applied",
        approvalInstanceId: null,
        errorCode: null,
        errorMessage: null,
      },
      {
        operation: "grant",
        subjectType: "user",
        subjectId: 7,
        relation: "editor",
        modelId: "editor",
        outcome: "failed",
        approvalInstanceId: null,
        errorCode: 21009,
        errorMessage: "failed",
      },
    ])).toEqual([grants[1]]);
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

  it("maps create result counts and item outcomes", async () => {
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: {
        id: 44,
        name: "Invites",
        auth_type: "public",
        initial_permission_result: {
          status: "success",
          error_code: null,
          direct_applied_count: 1,
          invite_created_count: 1,
          invite_existing_count: 1,
          failed_count: 0,
          results: [{
            operation: "grant",
            subject_type: "user",
            subject_id: 7,
            relation: "viewer",
            outcome: "invite_created",
            approval_instance_id: 1201,
          }],
        },
      },
    });

    const result = await createSpaceApi({ name: "Invites", auth_type: "public" });
    expect(result.initialPermissionResult).toMatchObject({
      status: "success",
      directAppliedCount: 1,
      inviteCreatedCount: 1,
      inviteExistingCount: 1,
      failedCount: 0,
      results: [{ subjectId: 7, outcome: "invite_created" }],
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
