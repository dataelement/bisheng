import request from "~/api/request";
import {
  applyResourcePermissionModeDraft,
  checkResourceAction,
  createResourcePermissionModeDraft,
  getGrantablePermissionModels,
  getMyResourcePermissions,
  getResourcePermissionContext,
  getResourcePermissionGrants,
  mutateResourceGrants,
} from "~/api/permission";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("F048 Client permission API", () => {
  beforeEach(() => {
    mockedRequest.get.mockResolvedValue({
      status_code: 200,
      status_message: "success",
      data: { ok: true },
    });
    mockedRequest.post.mockResolvedValue({
      status_code: 200,
      status_message: "success",
      data: { ok: true },
    });
  });

  it("uses the resource context, roster, summary, and grantable model paths", async () => {
    await getResourcePermissionContext("channel", "channel-1");
    await getResourcePermissionGrants("channel", "channel-1", {
      cursor: "next-token",
      page_size: 25,
    });
    await getMyResourcePermissions("channel", "channel-1");
    await getGrantablePermissionModels("channel", "channel-1");

    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/permissions/resources/channel/channel-1/context",
      { skip403Redirect: true },
    );
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/permissions/resources/channel/channel-1/grants",
      {
        params: { cursor: "next-token", page_size: 25 },
        skip403Redirect: true,
      },
    );
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      3,
      "/api/v1/permissions/resources/channel/channel-1/my-permissions",
      { skip403Redirect: true },
    );
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      4,
      "/api/v1/permissions/resources/channel/channel-1/grantable-models",
      { skip403Redirect: true },
    );
  });

  it("sends only stable IDs and versions in exact grant mutations", async () => {
    const payload = {
      idempotency_key: "mutation-1",
      expected_resource_version: 7,
      expected_catalog_release_id: 11,
      changes: [
        {
          op: "ADD" as const,
          model_key: "custom-reader",
          subject: {
            type: "department" as const,
            id: "42",
            userset_relation: "subtree_member",
            include_children: true,
          },
        },
        {
          op: "MOVE" as const,
          assignee_id: "8",
          expected_assignee_version: 3,
          target_model_key: "standard-editor",
        },
        {
          op: "REMOVE" as const,
          assignee_id: "9",
          expected_assignee_version: 4,
        },
      ],
    };

    await mutateResourceGrants("channel", "channel-1", payload);

    expect(mockedRequest.post).toHaveBeenCalledWith(
      "/api/v1/permissions/resources/channel/channel-1/grants:mutate",
      payload,
      { skip403Redirect: true },
    );
    const serialized = JSON.stringify(mockedRequest.post.mock.calls[0][1]);
    expect(serialized).not.toMatch(/"protected"|"source"|"derived_level"/);
  });

  it("uses server mode drafts and concrete action checks", async () => {
    await createResourcePermissionModeDraft("folder", "folder-1", {
      target_mode: "CUSTOM",
      expected_resource_version: 4,
      expected_catalog_release_id: 11,
    });
    await applyResourcePermissionModeDraft("folder", "folder-1", "draft-1", {
      idempotency_key: "mode-1",
      expected_resource_version: 4,
      expected_catalog_release_id: 11,
      confirmed: true,
    });
    await checkResourceAction({
      resource_type: "knowledge_file",
      resource_id: "file-1",
      action: "download",
    });

    expect(mockedRequest.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/permissions/resources/folder/folder-1/mode-drafts",
      {
        target_mode: "CUSTOM",
        expected_resource_version: 4,
        expected_catalog_release_id: 11,
      },
      { skip403Redirect: true },
    );
    expect(mockedRequest.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/permissions/resources/folder/folder-1/mode-drafts/draft-1/apply",
      {
        idempotency_key: "mode-1",
        expected_resource_version: 4,
        expected_catalog_release_id: 11,
        confirmed: true,
      },
      { skip403Redirect: true },
    );
    expect(mockedRequest.post).toHaveBeenNthCalledWith(
      3,
      "/api/v1/permissions/check",
      {
        resource_type: "knowledge_file",
        resource_id: "file-1",
        action: "download",
      },
      { skip403Redirect: true },
    );
  });
});
