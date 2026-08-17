import { useLocalize } from "~/hooks";
import { PermissionLevelMenu } from "./PermissionLevelMenu";
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
    if (row.protected || row.editable === false || !capabilities.canChangeRelation) return;
    const model = capabilities.relationModels.find((candidate) => candidate.id === modelId);
    if (!model) return;

    const rowKey = getPermissionDraftRowKey(row);
    onChange(value.map((candidate) => (
      getPermissionDraftRowKey(candidate) === rowKey
        ? { ...candidate, modelKey: model.id, modelName: model.name, modelLevel: model.level }
        : candidate
    )));
  };

  const handleRemove = (row: PermissionDraftRow) => {
    if (row.protected || row.editable === false || !capabilities.canRemove) return;
    const rowKey = getPermissionDraftRowKey(row);
    onChange(value.filter((candidate) => getPermissionDraftRowKey(candidate) !== rowKey));
  };

  return (
    <div className="flex flex-col divide-y divide-dashed divide-border-base">
      {value.map((row) => {
        const rowKey = getPermissionDraftRowKey(row);
        const relationModels = capabilities.relationModels;
        const canChangeRelation = !row.protected && row.editable !== false
          && capabilities.canChangeRelation
          && relationModels.length > 0;
        const canRemove = !row.protected && row.editable !== false && capabilities.canRemove;
        const activeModelId = row.modelKey;
        const relationLabel =
          capabilities.relationModels.find((model) => model.id === activeModelId)?.name
          ?? row.modelName
          ?? row.modelKey;

        return (
          <div key={rowKey} className="flex min-h-11 items-center gap-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-fill-4 text-caption text-white">
                {row.subjectName.trim().slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 truncate text-body text-text-1">{row.subjectName}</span>
            </div>
            {row.protected ? (
              <span className="inline-flex h-8 w-[96px] shrink-0 items-center justify-end whitespace-nowrap px-2 text-[14px] leading-[22px] text-[#999999]">
                {localize("creator")}
              </span>
            ) : (
              <PermissionLevelMenu
                label={relationLabel}
                options={relationModels}
                activeId={row.modelKey}
                canChangeLevel={canChangeRelation}
                onChange={(modelId) => handleRelationChange(row, modelId)}
                onRemove={canRemove ? () => handleRemove(row) : undefined}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
