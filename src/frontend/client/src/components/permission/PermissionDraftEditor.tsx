import { Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useLocalize } from "~/hooks";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { RelationSelect } from "./RelationSelect";
import type { RelationModelOption } from "./RelationSelect";
import {
  getPermissionDraftRowKey,
} from "./usePermissionDraft";
import type { PermissionDraftRow } from "./usePermissionDraft";

export interface PermissionDraftEditorCapabilities {
  canChangeRelation: boolean;
  canRemove: boolean;
  relationModels: RelationModelOption[];
}

export interface PermissionDraftEditorProps {
  value: PermissionDraftRow[];
  onChange: (value: PermissionDraftRow[]) => void;
  capabilities: PermissionDraftEditorCapabilities;
}

export function PermissionDraftEditor({
  value,
  onChange,
  capabilities,
}: PermissionDraftEditorProps) {
  const localize = useLocalize();

  const handleRelationChange = (row: PermissionDraftRow, modelId: string) => {
    if (row.immutableCreator || !capabilities.canChangeRelation) return;
    const model = capabilities.relationModels.find((candidate) => candidate.id === modelId);
    if (!model || (row.subjectType !== "user" && model.relation === "owner")) return;

    const rowKey = getPermissionDraftRowKey(row);
    onChange(value.map((candidate) => (
      getPermissionDraftRowKey(candidate) === rowKey
        ? { ...candidate, relation: model.relation, modelId: model.id }
        : candidate
    )));
  };

  const handleRemove = (row: PermissionDraftRow) => {
    if (row.immutableCreator || !capabilities.canRemove) return;
    const rowKey = getPermissionDraftRowKey(row);
    onChange(value.filter((candidate) => getPermissionDraftRowKey(candidate) !== rowKey));
  };

  return (
    <div className="flex flex-col divide-y divide-dashed divide-border-base">
      {value.map((row) => {
        const rowKey = getPermissionDraftRowKey(row);
        const relationModels = row.subjectType === "user"
          ? capabilities.relationModels
          : capabilities.relationModels.filter((model) => model.relation !== "owner");
        const canChangeRelation = !row.immutableCreator
          && capabilities.canChangeRelation
          && relationModels.length > 0;
        const canRemove = !row.immutableCreator && capabilities.canRemove;

        return (
          <div key={rowKey} className="flex min-h-11 items-center gap-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-fill-4 text-caption text-white">
                {row.subjectName.trim().slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 truncate text-body text-text-1">{row.subjectName}</span>
            </div>
            {row.immutableCreator ? (
              <span className="px-2 text-body text-[#999999]">{localize("creator")}</span>
            ) : (
              <RelationSelect
                value={row.modelId ?? row.relation}
                onChange={(modelId) => handleRelationChange(row, modelId)}
                options={relationModels}
                disabled={!canChangeRelation}
                className="w-32"
              />
            )}
            {canRemove && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    color="danger"
                    variant="text"
                    size="small"
                    iconOnly
                    aria-label={localize("com_permission.remove")}
                    onClick={() => handleRemove(row)}
                  >
                    <Outlined.Delete className="size-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{localize("com_permission.remove")}</TooltipContent>
              </Tooltip>
            )}
          </div>
        );
      })}
    </div>
  );
}
