/** @jest-environment node */

import request from "./request";
import {
  getCreationDepartmentChildren,
  getCreationPermissionContext,
  getAllResourcePermissionGrants,
  getResourcePermissionContext,
  mutateResourceGrants,
  searchCreationUsers,
} from "./permission";
import { createSpaceApi } from "./knowledge";
import { createManagerChannelApi } from "./channels";

jest.mock("./request", () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("F048 unified permission settings adapter", () => {
  beforeEach(() => jest.clearAllMocks());

  it.each([
    ["knowledge_space" as const, "/api/v1/knowledge/space"],
    ["channel" as const, "/api/v1/channel/manager"],
  ])("loads %s prospective context from its business domain", async (type, path) => {
    const controller = new AbortController();
    const context = {
      catalog_release_id: 42,
      can_configure_initial_permissions: true,
      grantable_models: [{ key: "viewer", name: "Viewer", level: 1, active: true }],
    };
    mockedRequest.get.mockResolvedValueOnce({ status_code: 200, data: context });

    await expect(getCreationPermissionContext(type, { signal: controller.signal }))
      .resolves.toEqual(context);
    expect(mockedRequest.get).toHaveBeenCalledWith(
      `${path}/creation-permission-context`,
      expect.objectContaining({ signal: controller.signal, skip403Redirect: true }),
    );
  });

  it("uses domain-scoped creation candidates and preserves abort signals", async () => {
    const controller = new AbortController();
    mockedRequest.get
      .mockResolvedValueOnce({ status_code: 200, data: { data: [{ user_id: 7 }], total: 1 } })
      .mockResolvedValueOnce({ status_code: 200, data: [{ id: 8, name: "Platform" }] });

    await searchCreationUsers("knowledge_space", "Ada", { page: 2, pageSize: 20 }, {
      signal: controller.signal,
    });
    await getCreationDepartmentChildren("channel", null, { signal: controller.signal });

    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge/space/creation-grant-subjects/users",
      expect.objectContaining({
        params: { keyword: "Ada", page: 2, page_size: 20 },
        signal: controller.signal,
      }),
    );
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/channel/manager/creation-grant-subjects/departments/children",
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("preserves F048 resource and catalog versions", async () => {
    mockedRequest.get.mockResolvedValueOnce({
      status_code: 200,
      data: {
        mode: "CUSTOM",
        parent_type: null,
        parent_id: null,
        resource_version: 9,
        catalog_release_id: 42,
        projection_state: "READY",
        can_manage_permission: true,
      },
    });
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: { resource_version: 10, items: [] },
    });

    await expect(getResourcePermissionContext("channel", "c-1"))
      .resolves.toMatchObject({ resource_version: 9, catalog_release_id: 42 });
    await expect(mutateResourceGrants("channel", "c-1", {
      idempotency_key: "mutation-1",
      expected_resource_version: 9,
      expected_catalog_release_id: 42,
      changes: [],
    })).resolves.toMatchObject({ resource_version: 10 });
  });

  it("loads every cursor page without merging assignee sources", async () => {
    mockedRequest.get
      .mockResolvedValueOnce({
        status_code: 200,
        data: {
          data: [{ assignee_id: "direct-1", source: { type: "DIRECT" } }],
          page_size: 200,
          has_more: true,
          next_cursor: "cursor-2",
        },
      })
      .mockResolvedValueOnce({
        status_code: 200,
        data: {
          data: [{ assignee_id: "department-1", source: { type: "DEPARTMENT" } }],
          page_size: 200,
          has_more: false,
          next_cursor: null,
        },
      });

    await expect(getAllResourcePermissionGrants("knowledge_space", "space-1"))
      .resolves.toMatchObject([
        { assignee_id: "direct-1", source: { type: "DIRECT" } },
        { assignee_id: "department-1", source: { type: "DEPARTMENT" } },
      ]);
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/permissions/resources/knowledge_space/space-1/grants",
      expect.objectContaining({ params: { cursor: "cursor-2", page_size: 200 } }),
    );
  });

  it("maps knowledge creation options and partial success", async () => {
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: {
        id: 42,
        name: "Docs",
        auth_type: "public",
        initial_permission_result: {
          status: "failed",
          resource_version: 3,
          assignee_ids: [],
          error_code: 21009,
        },
      },
    });
    const initialPermissions = {
      expected_catalog_release_id: 42,
      grants: [{ model_key: "viewer", subject: { type: "user" as const, id: "7" } }],
    };
    const result = await createSpaceApi({
      name: "Docs",
      auth_type: "public",
      creationRequestId: "request-1",
      initialPermissions,
    });

    expect(mockedRequest.post).toHaveBeenCalledWith("/api/v1/knowledge/space", {
      name: "Docs",
      auth_type: "public",
      creation_request_id: "request-1",
      initial_permissions: initialPermissions,
    });
    expect(result.initialPermissionResult).toEqual({
      status: "failed",
      resourceVersion: 3,
      assigneeIds: [],
      errorCode: 21009,
    });
  });

  it("keeps channel business fields while adding creation permissions", async () => {
    mockedRequest.post.mockResolvedValueOnce({
      status_code: 200,
      data: { id: "channel-1", name: "News", initial_permission_result: { status: "succeeded" } },
    });
    const initialPermissions = {
      expected_catalog_release_id: 42,
      grants: [{
        model_key: "editor",
        subject: { type: "department" as const, id: "8", include_children: true },
      }],
    };
    await createManagerChannelApi({
      name: "News",
      source_list: ["source-1"],
      visibility: "public",
      filter_rules: [],
      knowledge_sync: { main: { enabled: false, spaces: [] }, subs: [] },
      creationRequestId: "request-2",
      initialPermissions,
    });

    expect(mockedRequest.post).toHaveBeenCalledWith(
      "/api/v1/channel/manager/create",
      expect.objectContaining({
        source_list: ["source-1"],
        filter_rules: [],
        knowledge_sync: { main: { enabled: false, spaces: [] }, subs: [] },
        creation_request_id: "request-2",
        initial_permissions: initialPermissions,
      }),
      expect.objectContaining({ showError: true }),
    );
  });

  it("keeps legacy create bodies unchanged when optional fields are omitted", async () => {
    mockedRequest.post
      .mockResolvedValueOnce({ status_code: 200, data: { id: 1, name: "Legacy", auth_type: "private" } })
      .mockResolvedValueOnce({ status_code: 200, data: { id: "c-2", name: "Legacy channel" } });
    await createSpaceApi({ name: "Legacy", auth_type: "private" });
    await createManagerChannelApi({
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
  });
});
