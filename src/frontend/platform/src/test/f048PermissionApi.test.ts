import {
  applyResourcePermissionModeDraftApi,
  checkResourceActionApi,
  createPermissionCatalogDraftApi,
  createResourcePermissionModeDraftApi,
  getGrantablePermissionModelsApi,
  getMyResourcePermissionsApi,
  getPermissionCatalogApi,
  getPermissionCatalogDraftApi,
  getResourcePermissionContextApi,
  getResourcePermissionGrantsApi,
  mutateResourceGrantsApi,
  publishPermissionCatalogDraftApi,
  type GrantablePermissionModel,
  type PermissionCatalogModel,
  type PermissionGrantAssignee,
} from "@/controllers/API/permission";
import { beforeEach, describe, expect, it, vi } from "vitest";

const requestMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  default: requestMocks,
}));

describe("F048 Platform permission API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("preserves server-owned pure visibility metadata and its original level", async () => {
    const catalogModel: PermissionCatalogModel = {
      key: "original-use-only",
      name: "Original model",
      kind: "CUSTOM",
      config_scope: "PLATFORM",
      derived_level: 3,
      active: true,
      allow_same_level: false,
      action_codes: [],
      version: 8,
      visibility_only_resource_types: ["tool", "linsight_skill"],
      visibility_level: 3,
    };
    const model: GrantablePermissionModel = {
      key: "original-use-only",
      name: "Original model",
      level: 3,
      active: true,
      visibility_only: true,
    };
    const assignee: PermissionGrantAssignee = {
      assignee_id: "source-1",
      assignee_version: 4,
      subject: { type: "user", id: "7", name: "Reader" },
      model: { ...model, active: false },
      source: { type: "DIRECT", include_children: false },
      scope: "LOCAL",
      inherited_from: null,
      protected: false,
      editable: true,
    };
    const catalog = { models: [catalogModel] };
    const roster = {
      data: [assignee],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    };
    requestMocks.get
      .mockResolvedValueOnce(catalog)
      .mockResolvedValueOnce([model])
      .mockResolvedValueOnce(roster);
    const read = await getPermissionCatalogApi();
    expect(read).toBe(catalog);
    expect(read.models[0].visibility_only_resource_types).toEqual([
      "tool",
      "linsight_skill",
    ]);
    expect(read.models[0].visibility_level).toBe(3);
    expect(await getGrantablePermissionModelsApi("tool", "tool-1")).toEqual([
      model,
    ]);
    const page = await getResourcePermissionGrantsApi("tool", "tool-1");
    expect(page).toBe(roster);
    expect(page.data[0].model.visibility_only).toBe(true);
    expect(page.data[0].model.level).toBe(3);
    expect(page.data[0].model.active).toBe(false);
    expect(page.data[0].assignee_id).toBe("source-1");
  });

  it("writes only stable model/source identities after reading a pure visibility model", async () => {
    const model: GrantablePermissionModel = {
      key: "pure-at-original-level",
      name: "Pure model",
      level: 3,
      active: true,
      visibility_only: true,
    };
    requestMocks.get.mockResolvedValueOnce([model]);
    requestMocks.post.mockResolvedValueOnce({ resource_version: 8, items: [] });
    const [serverModel] = await getGrantablePermissionModelsApi(
      "tool",
      "tool-1",
    );
    await mutateResourceGrantsApi("tool", "tool-1", {
      idempotency_key: "pure-grant",
      expected_resource_version: 7,
      expected_catalog_release_id: 12,
      changes: [
        {
          op: "ADD",
          model_key: serverModel.key,
          subject: { type: "user", id: "7" },
        },
      ],
    });
    const body = requestMocks.post.mock.calls[0][1];
    expect(body).toEqual({
      idempotency_key: "pure-grant",
      expected_resource_version: 7,
      expected_catalog_release_id: 12,
      changes: [
        {
          op: "ADD",
          model_key: "pure-at-original-level",
          subject: { type: "user", id: "7" },
        },
      ],
    });
    expect(JSON.stringify(body)).not.toMatch(
      /visibility_only|visibility_level|action_codes|"level"|"use"|"visible"/,
    );
  });

  it("uses the Catalog draft and publish contracts", async () => {
    requestMocks.get.mockResolvedValue({ id: 12 });
    requestMocks.post.mockResolvedValue({ draft_id: 13 });

    await getPermissionCatalogApi();
    await createPermissionCatalogDraftApi({
      idempotency_key: "draft-1",
      base_release_id: 12,
      changes: [
        {
          type: "ASSIGN_ACTION_LEVEL",
          action_code: "edit",
          level: 2,
        },
      ],
    });
    await getPermissionCatalogDraftApi(13);
    await publishPermissionCatalogDraftApi(13, {
      expected_current_release_id: 12,
      idempotency_key: "publish-1",
      confirmed: true,
    });

    expect(requestMocks.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/permissions/catalog",
    );
    expect(requestMocks.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/permissions/catalog/drafts",
      expect.objectContaining({ base_release_id: 12 }),
      // Off unless a caller asks for the envelope to explain a failure.
      { silent: undefined },
    );
    expect(requestMocks.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/permissions/catalog/drafts/13",
    );
    expect(requestMocks.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/permissions/catalog/drafts/13/publish",
      {
        expected_current_release_id: 12,
        idempotency_key: "publish-1",
        confirmed: true,
      },
      // Off unless a caller asks for the envelope to explain a failure.
      { silent: undefined },
    );
  });

  it("uses cursor roster, self summary, and grant mutation contracts", async () => {
    requestMocks.get.mockResolvedValue({});
    requestMocks.post.mockResolvedValue({});
    const root = "/api/v1/permissions/resources/knowledge_file/file-1";

    await getGrantablePermissionModelsApi("knowledge_file", "file-1");
    await getResourcePermissionContextApi("knowledge_file", "file-1");
    await getResourcePermissionGrantsApi("knowledge_file", "file-1", {
      cursor: "opaque-next",
      page_size: 25,
    });
    await getMyResourcePermissionsApi("knowledge_file", "file-1");
    await mutateResourceGrantsApi("knowledge_file", "file-1", {
      idempotency_key: "grant-1",
      expected_resource_version: 7,
      expected_catalog_release_id: 12,
      changes: [
        {
          op: "ADD",
          model_key: "viewer",
          subject: {
            type: "department",
            id: "17",
            userset_relation: "subtree_member",
            include_children: true,
          },
        },
        {
          op: "MOVE",
          assignee_id: "91",
          expected_assignee_version: 2,
          target_model_key: "editor",
        },
        {
          op: "REMOVE",
          assignee_id: "92",
          expected_assignee_version: 3,
        },
      ],
    });

    expect(requestMocks.get).toHaveBeenNthCalledWith(
      1,
      `${root}/grantable-models`,
    );
    expect(requestMocks.get).toHaveBeenNthCalledWith(2, `${root}/context`);
    expect(requestMocks.get).toHaveBeenNthCalledWith(3, `${root}/grants`, {
      params: { cursor: "opaque-next", page_size: 25 },
    });
    expect(requestMocks.get).toHaveBeenNthCalledWith(
      4,
      `${root}/my-permissions`,
    );
    const mutationBody = requestMocks.post.mock.calls[0][1];
    expect(requestMocks.post).toHaveBeenCalledWith(
      `${root}/grants:mutate`,
      mutationBody,
    );
    expect(JSON.stringify(mutationBody)).not.toMatch(
      /"protected"|"source_type"|"derived_level"|"level"|"permission_id"/,
    );
    for (const change of mutationBody.changes) {
      expect(change).not.toHaveProperty("relation");
    }
  });

  it("uses server-side mode drafts and concrete action checks", async () => {
    requestMocks.post.mockResolvedValue({});
    const root = "/api/v1/permissions/resources/knowledge_file/file-1";

    await createResourcePermissionModeDraftApi("knowledge_file", "file-1", {
      target_mode: "CUSTOM",
      expected_resource_version: 7,
      expected_catalog_release_id: 12,
    });
    await applyResourcePermissionModeDraftApi(
      "knowledge_file",
      "file-1",
      "mode-1",
      {
        idempotency_key: "mode-apply-1",
        expected_resource_version: 7,
        expected_catalog_release_id: 12,
        confirmed: true,
      },
    );
    await checkResourceActionApi({
      resource_type: "knowledge_file",
      resource_id: "file-1",
      action: "download",
    });

    expect(requestMocks.post).toHaveBeenNthCalledWith(
      1,
      `${root}/mode-drafts`,
      expect.objectContaining({ target_mode: "CUSTOM" }),
    );
    expect(requestMocks.post).toHaveBeenNthCalledWith(
      2,
      `${root}/mode-drafts/mode-1/apply`,
      expect.objectContaining({ confirmed: true }),
    );
    expect(requestMocks.post).toHaveBeenNthCalledWith(
      3,
      "/api/v1/permissions/check",
      {
        resource_type: "knowledge_file",
        resource_id: "file-1",
        action: "download",
      },
    );
  });
});
