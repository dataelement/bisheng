import {
  filterPermissionModelsWithScopeItems,
  getPermissionModelScopeGroups,
  getPermissionModelScopeItems,
  hasPermissionModelScopeItems,
} from "./permissionModelInfo";
import type { ResourceType } from "~/api/permission";
import type { RelationModelOption } from "./RelationSelect";

function itemIds(resourceType: ResourceType, model: RelationModelOption) {
  return getPermissionModelScopeItems(resourceType, model)?.map((item) => item.id) ?? [];
}

function groupedItemIds(resourceType: ResourceType, model: RelationModelOption) {
  return (getPermissionModelScopeGroups(resourceType, model) ?? []).map((group) => ({
    scope: group.scope,
    ids: group.items.map((item) => item.id),
  }));
}

describe("permission model scope info", () => {
  it("shows space grants across space, folder, and file scopes", () => {
    expect(groupedItemIds("knowledge_space", {
      id: "manager",
      name: "Manager",
      relation: "manager",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    })).toEqual([
      {
        scope: "space",
        ids: [
          "view_space",
          "edit_space",
          "create_folder",
          "upload_file_to_space",
          "publish_file",
          "manage_space_relation",
        ],
      },
      {
        scope: "folder",
        ids: [
          "view_folder",
          "upload_file_to_folder",
          "rename_folder",
          "download_folder",
          "move_folder",
          "manage_folder_relation",
        ],
      },
      {
        scope: "file",
        ids: [
          "view_file",
          "rename_file",
          "download_file",
          "move_file",
          "share_file",
          "manage_file_relation",
        ],
      },
    ]);
  });

  it("shows folder grants across folder and descendant file scopes", () => {
    expect(groupedItemIds("folder", {
      id: "editor",
      name: "Editor",
      relation: "editor",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    })).toEqual([
      {
        scope: "folder",
        ids: [
          "view_folder",
          "upload_file_to_folder",
          "rename_folder",
          "download_folder",
          "move_folder",
        ],
      },
      {
        scope: "file",
        ids: [
          "view_file",
          "rename_file",
          "download_file",
          "move_file",
        ],
      },
    ]);
  });

  it("filters explicit custom permissions to file scope", () => {
    expect(itemIds("knowledge_file", {
      id: "custom_file",
      name: "Custom File",
      relation: "manager",
      permissions: ["view_file", "delete_file", "view_folder", "share_file"],
      permissions_explicit: true,
      is_system: false,
    })).toEqual(["view_file", "delete_file", "share_file"]);
  });

  it("defaults file sharing to managers and owners only", () => {
    const systemModel = (relation: RelationModelOption["relation"]): RelationModelOption => ({
      id: relation,
      name: relation,
      relation,
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    });

    expect(itemIds("knowledge_file", systemModel("viewer"))).not.toContain("share_file");
    expect(itemIds("knowledge_file", systemModel("editor"))).not.toContain("share_file");
    expect(itemIds("knowledge_file", systemModel("manager"))).toContain("share_file");
    expect(itemIds("knowledge_file", systemModel("owner"))).toContain("share_file");
  });

  it("keeps space and folder upload permissions independently configurable", () => {
    expect(groupedItemIds("knowledge_space", {
      id: "space_upload_only",
      name: "Space upload only",
      relation: "editor",
      permissions: ["upload_file_to_space"],
      permissions_explicit: true,
      is_system: false,
    })).toEqual([
      {
        scope: "space",
        ids: ["upload_file_to_space"],
      },
    ]);

    expect(groupedItemIds("knowledge_space", {
      id: "folder_upload_only",
      name: "Folder upload only",
      relation: "editor",
      permissions: ["upload_file_to_folder"],
      permissions_explicit: true,
      is_system: false,
    })).toEqual([
      {
        scope: "folder",
        ids: ["upload_file_to_folder"],
      },
    ]);
  });

  it("keeps descendant-only models available for parent resource grants", () => {
    const emptyFileModel: RelationModelOption = {
      id: "folder_only",
      name: "Folder Only",
      relation: "editor",
      permissions: ["view_folder"],
      permissions_explicit: true,
      is_system: false,
    };
    const fileModel: RelationModelOption = {
      id: "file_editor",
      name: "File Editor",
      relation: "editor",
      permissions: ["rename_file"],
      permissions_explicit: true,
      is_system: false,
    };

    expect(itemIds("knowledge_file", emptyFileModel)).toEqual([]);
    expect(hasPermissionModelScopeItems("knowledge_file", emptyFileModel)).toBe(false);
    expect(filterPermissionModelsWithScopeItems("knowledge_file", [
      emptyFileModel,
      fileModel,
    ])).toEqual([fileModel]);
    expect(hasPermissionModelScopeItems("folder", fileModel)).toBe(true);
    expect(filterPermissionModelsWithScopeItems("folder", [fileModel])).toEqual([fileModel]);
  });
});
