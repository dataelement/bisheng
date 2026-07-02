import {
  filterPermissionModelsWithScopeItems,
  getPermissionModelScopeItems,
  hasPermissionModelScopeItems,
} from "./permissionModelInfo";
import type { ResourceType } from "~/api/permission";
import type { RelationModelOption } from "./RelationSelect";

function itemIds(resourceType: ResourceType, model: RelationModelOption) {
  return getPermissionModelScopeItems(resourceType, model)?.map((item) => item.id) ?? [];
}

describe("permission model scope info", () => {
  it("derives system model permissions for knowledge space scope only", () => {
    expect(itemIds("knowledge_space", {
      id: "manager",
      name: "Manager",
      relation: "manager",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    })).toEqual([
      "view_space",
      "edit_space",
      "create_folder",
      "upload_file",
      "publish_file",
      "share_space",
      "manage_space_relation",
    ]);
  });

  it("derives system model permissions for folder scope only", () => {
    expect(itemIds("folder", {
      id: "editor",
      name: "Editor",
      relation: "editor",
      permissions: [],
      permissions_explicit: false,
      is_system: true,
    })).toEqual([
      "view_folder",
      "rename_folder",
      "download_folder",
      "move_folder",
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
    })).toEqual(["view_file", "delete_file"]);
  });

  it("identifies and filters models without current resource permission items", () => {
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
  });
});
