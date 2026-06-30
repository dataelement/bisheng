import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { cn } from "~/utils";
import type { RelationLevel, ResourceType } from "~/api/permission";
import type { RelationModelOption } from "./RelationSelect";

type PermissionRelation = "can_read" | "can_edit" | "can_manage" | "can_delete";

interface PermissionScopeItem {
  id: string;
  labelKey: string;
  relation: PermissionRelation;
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

const KNOWLEDGE_PERMISSION_ITEMS: Record<
  Extract<ResourceType, "knowledge_space" | "folder" | "knowledge_file">,
  PermissionScopeItem[]
> = {
  knowledge_space: [
    { id: "view_space", labelKey: "com_permission.permission_item_view_space", relation: "can_read" },
    { id: "edit_space", labelKey: "com_permission.permission_item_edit_space", relation: "can_edit" },
    { id: "create_folder", labelKey: "com_permission.permission_item_create_folder", relation: "can_edit" },
    { id: "upload_file", labelKey: "com_permission.permission_item_upload_file", relation: "can_edit" },
    { id: "delete_space", labelKey: "com_permission.permission_item_delete_space", relation: "can_delete" },
    { id: "share_space", labelKey: "com_permission.permission_item_share_space", relation: "can_manage" },
    {
      id: "manage_space_relation",
      labelKey: "com_permission.permission_item_manage_space_relation",
      relation: "can_manage",
    },
  ],
  folder: [
    { id: "view_folder", labelKey: "com_permission.permission_item_view_folder", relation: "can_read" },
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
  knowledge_file: [
    { id: "view_file", labelKey: "com_permission.permission_item_view_file", relation: "can_read" },
    { id: "rename_file", labelKey: "com_permission.permission_item_rename_file", relation: "can_edit" },
    { id: "delete_file", labelKey: "com_permission.permission_item_delete_file", relation: "can_delete" },
    { id: "download_file", labelKey: "com_permission.permission_item_download_file", relation: "can_read" },
    { id: "move_file", labelKey: "com_permission.permission_item_move_file", relation: "can_edit" },
    {
      id: "manage_file_relation",
      labelKey: "com_permission.permission_item_manage_file_relation",
      relation: "can_manage",
    },
  ],
};

function isKnowledgePermissionResource(
  resourceType: ResourceType,
): resourceType is keyof typeof KNOWLEDGE_PERMISSION_ITEMS {
  return resourceType in KNOWLEDGE_PERMISSION_ITEMS;
}

function defaultPermissionIdsForRelation(
  resourceType: ResourceType,
  relation: RelationLevel,
) {
  if (!isKnowledgePermissionResource(resourceType)) return [];
  const modelLevel = MODEL_LEVEL[relation] ?? 0;
  return KNOWLEDGE_PERMISSION_ITEMS[resourceType]
    .filter((item) => modelLevel >= (RELATION_LEVEL[item.relation] ?? 99))
    .map((item) => item.id);
}

export function getPermissionModelScopeItems(
  resourceType: ResourceType,
  model: RelationModelOption,
) {
  if (!isKnowledgePermissionResource(resourceType)) return null;
  const scopeItems = KNOWLEDGE_PERMISSION_ITEMS[resourceType];
  const permissionIds =
    model.permissions_explicit === true
      ? model.permissions ?? []
      : model.is_system
        ? defaultPermissionIdsForRelation(resourceType, model.relation)
        : model.permissions ?? [];
  const permissionIdSet = new Set(permissionIds);
  return scopeItems.filter((item) => permissionIdSet.has(item.id));
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
  const items = getPermissionModelScopeItems(resourceType, model);
  if (items === null) return null;

  const labels = items.map((item) => localize(item.labelKey));
  const summary = labels.length ? labels.join("、") : localize("com_permission.model_scope_empty");

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          aria-hidden="true"
          data-testid={`permission-model-help-${resourceType}-${model.id}`}
          data-permission-summary={summary}
          className={cn(
            "ml-1 inline-flex size-4 shrink-0 items-center justify-center rounded-full text-[14px] font-semibold leading-4 text-[#F53F3F]",
            className,
          )}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          ?
        </span>
      </TooltipTrigger>
      <TooltipContent
        side="top"
        noArrow
        className="z-[140] max-w-[280px] bg-white text-[#212121] shadow-md"
      >
        <div className="space-y-1 text-left">
          <p className="text-[12px] font-medium leading-5">
            {localize("com_permission.model_scope_title")}
          </p>
          <p className="text-[12px] leading-5 text-[#4E5969]">
            {summary}
          </p>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
