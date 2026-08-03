import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { cn } from "~/utils";
import { Info } from "lucide-react";
import type { RelationLevel, ResourceType } from "~/api/permission";
import type { RelationModelOption } from "./RelationSelect";

type PermissionRelation = "can_read" | "can_edit" | "can_manage" | "can_delete";

interface PermissionScopeItem {
  id: string;
  labelKey: string;
  relation: PermissionRelation;
}

type KnowledgePermissionScope = "space" | "folder" | "file";

export interface PermissionScopeGroup {
  scope: KnowledgePermissionScope;
  labelKey: string;
  items: PermissionScopeItem[];
}

const RELATION_LEVEL: Record<PermissionRelation, number> = {
  can_read: 1,
  can_edit: 2,
  can_manage: 3,
  can_delete: 4,
};

const MODEL_LEVEL: Record<RelationLevel, number> = {
  viewer: 1,
  editor: 2,
  manager: 3,
  owner: 4,
};

const KNOWLEDGE_PERMISSION_GROUPS: PermissionScopeGroup[] = [
  {
    scope: "space",
    labelKey: "com_permission.permission_scope_space",
    items: [
      { id: "view_space", labelKey: "com_permission.permission_item_view_space", relation: "can_read" },
      { id: "edit_space", labelKey: "com_permission.permission_item_edit_space", relation: "can_edit" },
      { id: "create_folder", labelKey: "com_permission.permission_item_create_folder", relation: "can_edit" },
      {
        id: "upload_file_to_space",
        labelKey: "com_permission.permission_item_upload_file",
        relation: "can_edit",
      },
      { id: "publish_file", labelKey: "com_permission.permission_item_publish_file", relation: "can_edit" },
      { id: "delete_space", labelKey: "com_permission.permission_item_delete_space", relation: "can_delete" },
      {
        id: "manage_space_relation",
        labelKey: "com_permission.permission_item_manage_space_relation",
        relation: "can_manage",
      },
    ],
  },
  {
    scope: "folder",
    labelKey: "com_permission.permission_scope_folder",
    items: [
      { id: "view_folder", labelKey: "com_permission.permission_item_view_folder", relation: "can_read" },
      {
        id: "upload_file_to_folder",
        labelKey: "com_permission.permission_item_upload_file",
        relation: "can_edit",
      },
      {
        id: "rename_folder",
        labelKey: "com_permission.permission_item_rename_folder",
        relation: "can_edit",
      },
      { id: "delete_folder", labelKey: "com_permission.permission_item_delete_folder", relation: "can_delete" },
      {
        id: "download_folder",
        labelKey: "com_permission.permission_item_download_folder",
        relation: "can_read",
      },
      { id: "move_folder", labelKey: "com_permission.permission_item_move_folder", relation: "can_edit" },
      {
        id: "manage_folder_relation",
        labelKey: "com_permission.permission_item_manage_folder_relation",
        relation: "can_manage",
      },
    ],
  },
  {
    scope: "file",
    labelKey: "com_permission.permission_scope_file",
    items: [
      { id: "view_file", labelKey: "com_permission.permission_item_view_file", relation: "can_read" },
      { id: "rename_file", labelKey: "com_permission.permission_item_rename_file", relation: "can_edit" },
      { id: "delete_file", labelKey: "com_permission.permission_item_delete_file", relation: "can_delete" },
      { id: "download_file", labelKey: "com_permission.permission_item_download_file", relation: "can_read" },
      { id: "move_file", labelKey: "com_permission.permission_item_move_file", relation: "can_edit" },
      { id: "share_file", labelKey: "com_permission.permission_item_share_file", relation: "can_manage" },
      {
        id: "manage_file_relation",
        labelKey: "com_permission.permission_item_manage_file_relation",
        relation: "can_manage",
      },
    ],
  },
];

const VISIBLE_SCOPES_BY_RESOURCE: Record<
  Extract<ResourceType, "knowledge_space" | "folder" | "knowledge_file">,
  KnowledgePermissionScope[]
> = {
  knowledge_space: ["space", "folder", "file"],
  folder: ["folder", "file"],
  knowledge_file: ["file"],
};

function isKnowledgePermissionResource(
  resourceType: ResourceType,
): resourceType is keyof typeof VISIBLE_SCOPES_BY_RESOURCE {
  return resourceType in VISIBLE_SCOPES_BY_RESOURCE;
}

function defaultPermissionIdsForRelation(
  relation: RelationLevel,
) {
  const modelLevel = MODEL_LEVEL[relation] ?? 0;
  return KNOWLEDGE_PERMISSION_GROUPS
    .flatMap((group) => group.items)
    .filter((item) => modelLevel >= (RELATION_LEVEL[item.relation] ?? 99))
    .map((item) => item.id);
}

export function getPermissionModelScopeGroups(
  resourceType: ResourceType,
  model: RelationModelOption,
) {
  if (!isKnowledgePermissionResource(resourceType)) return null;
  const permissionIds =
    model.permissions_explicit === true
      ? model.permissions ?? []
      : model.is_system
        ? defaultPermissionIdsForRelation(model.relation)
        : model.permissions ?? [];
  const permissionIdSet = new Set(permissionIds);
  const visibleScopes = new Set(VISIBLE_SCOPES_BY_RESOURCE[resourceType]);
  return KNOWLEDGE_PERMISSION_GROUPS
    .filter((group) => visibleScopes.has(group.scope))
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => permissionIdSet.has(item.id)),
    }))
    .filter((group) => group.items.length > 0);
}

export function getPermissionModelScopeItems(
  resourceType: ResourceType,
  model: RelationModelOption,
) {
  const groups = getPermissionModelScopeGroups(resourceType, model);
  return groups?.flatMap((group) => group.items) ?? null;
}

export function hasPermissionModelScopeItems(
  resourceType: ResourceType,
  model: RelationModelOption,
) {
  const groups = getPermissionModelScopeGroups(resourceType, model);
  return groups === null || groups.length > 0;
}

export function filterPermissionModelsWithScopeItems(
  resourceType: ResourceType,
  models: RelationModelOption[],
) {
  return models.filter((model) => hasPermissionModelScopeItems(resourceType, model));
}

interface PermissionModelHelpIconProps {
  resourceType: ResourceType;
  model: RelationModelOption;
  localize: (key: string) => string;
  className?: string;
}

export function PermissionModelHelpIcon({
  resourceType,
  model,
  localize,
  className,
}: PermissionModelHelpIconProps) {
  const groups = getPermissionModelScopeGroups(resourceType, model);
  if (groups === null || groups.length === 0) return null;

  const localizedGroups = groups.map((group) => ({
    ...group,
    label: localize(group.labelKey),
    itemLabels: group.items.map((item) => localize(item.labelKey)),
  }));
  const summary = localizedGroups
    .map((group) => `${group.label}：${group.itemLabels.join("、")}`)
    .join("；");
  const title = localize("com_permission.permission_model_help_title");

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          data-testid={`permission-model-help-${resourceType}-${model.id}`}
          data-permission-summary={summary}
          aria-label={title}
          className={cn(
            "ml-1 shrink-0 cursor-pointer",
            className,
          )}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <Info
            className="size-4 text-[#86909c] outline-none hover:text-[#165dff]"
            aria-hidden="true"
          />
        </button>
      </TooltipTrigger>
      <TooltipContent
        side="left"
        sideOffset={8}
        noArrow
        className="z-[140] max-h-[320px] w-[360px] max-w-[calc(100vw-32px)] overflow-y-auto rounded-[8px] border border-[#E5E6EB] bg-white p-3 text-[#212121] shadow-[0_6px_20px_rgba(29,33,41,0.12)]"
      >
        <div className="space-y-3 text-left">
          <p className="text-[13px] font-medium leading-5 text-[#1D2129]">{title}</p>
          <div className="space-y-2.5">
            {localizedGroups.map((group) => (
              <div key={group.scope} className="grid grid-cols-[52px_minmax(0,1fr)] gap-2">
                <span className="pt-px text-[12px] font-medium leading-5 text-[#4E5969]">
                  {group.label}
                </span>
                <p className="break-words text-[12px] leading-5 text-[#4E5969]">
                  {group.itemLabels.join("、")}
                </p>
              </div>
            ))}
          </div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
