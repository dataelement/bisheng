import { useLocalize } from "~/hooks";
import { PermissionLevelMenu } from "./PermissionLevelMenu";
import { canMutatePermissionDraftRow } from "./permissionDraftPolicy";
import type { RelationModelOption } from "./RelationSelect";
import {
  getPermissionDraftRowKey,
} from "./usePermissionDraft";
import type { PermissionDraftRow } from "./usePermissionDraft";
import { SourceBadge } from "./SourceBadge";

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
    if (
      !canMutatePermissionDraftRow(
        row,
        capabilities.canChangeRelation,
        capabilities.relationModels,
      )
    ) return;
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
    if (
      !canMutatePermissionDraftRow(
        row,
        capabilities.canRemove,
        capabilities.relationModels,
      )
    ) return;
    const rowKey = getPermissionDraftRowKey(row);
    onChange(value.filter((candidate) => getPermissionDraftRowKey(candidate) !== rowKey));
  };

  return (
    <div className="flex flex-col divide-y divide-dashed divide-border-base">
      {value.map((row) => {
        const rowKey = getPermissionDraftRowKey(row);
        const relationModels = capabilities.relationModels;
        const canChangeRelation = canMutatePermissionDraftRow(
          row,
          capabilities.canChangeRelation,
          relationModels,
        );
        const canRemove = canMutatePermissionDraftRow(
          row,
          capabilities.canRemove,
          relationModels,
        );
        const activeModelId = row.modelKey;
        const relationLabel =
          capabilities.relationModels.find((model) => model.id === activeModelId)?.name
          ?? row.modelName
          ?? row.modelKey;
        // Meta line under the name. A protected row no longer prints the
        // protected tag —
        // the frozen relation label on the right already says it can't change —
        // so only these three can put something on the line.
        const showReadOnly =
          !row.protected && (row.scope === "INHERITED" || row.editable === false);
        const showInheritedFrom = row.scope === "INHERITED" && !!row.inheritedFromName;
        const hasMeta = !!row.sourceType || showReadOnly || showInheritedFrom;

        return (
          <div key={rowKey} className="flex min-h-11 items-center gap-3 py-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-fill-4 text-caption text-white">
                {row.subjectName.trim().slice(0, 1).toUpperCase()}
              </span>
              {/* Name and its meta (source tag, read-only note) sit on one line:
                  the name truncates, the meta keeps its width. */}
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <div className="min-w-0 truncate text-body text-text-1">{row.subjectName}</div>
                {hasMeta && (
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5 text-caption text-text-3">
                    {row.sourceType && (
                      <SourceBadge
                        source={{
                          type: row.sourceType,
                          include_children: Boolean(row.includeChildren),
                        }}
                      />
                    )}
                    {showReadOnly && (
                      <span>{localize("f048_permission.roster.read_only")}</span>
                    )}
                    {showInheritedFrom && (
                      <span>
                        {localize("f048_permission.roster.inherited_from")}: {row.inheritedFromName}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
            {row.protected ? (
              <span className="inline-flex h-8 w-[96px] shrink-0 items-center justify-end whitespace-nowrap px-2 text-[14px] leading-[22px] text-[#999999]">
                {relationLabel}
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
