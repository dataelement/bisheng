import { AlertTriangle, Loader2 } from "lucide-react";
import { useState } from "react";
import {
  applyResourcePermissionModeDraft,
  createResourcePermissionModeDraft,
} from "~/api/permission";
import type {
  ApplyPermissionModeDraftResult,
  PermissionModeDraft,
  ResourcePermissionContext,
  ResourcePermissionMode,
  ResourceType,
} from "~/api/permission";
import { Button } from "~/components/ui";
import { useLocalize } from "~/hooks";

interface ModeHeaderProps {
  resourceType: ResourceType;
  resourceId: string;
  context: ResourcePermissionContext;
  onApplied: (result: ApplyPermissionModeDraftResult) => void | Promise<void>;
}

function createIdempotencyKey(): string {
  return `mode-apply-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

export function ModeHeader({
  resourceType,
  resourceId,
  context,
  onApplied,
}: ModeHeaderProps) {
  const localize = useLocalize();
  const [draft, setDraft] = useState<PermissionModeDraft | null>(null);
  const [creating, setCreating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [conflict, setConflict] = useState(false);

  const targetMode: ResourcePermissionMode =
    context.mode === "CUSTOM" ? "INHERIT" : "CUSTOM";
  const expired =
    draft !== null &&
    new Date(draft.expires_at).getTime() <= new Date().getTime();
  const canSwitch =
    Boolean(context.parent_type && context.parent_id) &&
    context.can_manage_permission;

  const handleCreateDraft = async () => {
    if (!canSwitch || creating) return;
    setCreating(true);
    setConflict(false);
    try {
      setDraft(
        await createResourcePermissionModeDraft(resourceType, resourceId, {
          target_mode: targetMode,
          expected_resource_version: context.resource_version,
          expected_catalog_release_id: context.catalog_release_id,
        }),
      );
    } catch {
      setConflict(true);
    } finally {
      setCreating(false);
    }
  };

  const handleApply = async () => {
    if (!draft || applying || expired) return;
    setApplying(true);
    setConflict(false);
    try {
      const result = await applyResourcePermissionModeDraft(
        resourceType,
        resourceId,
        draft.draft_id,
        {
          idempotency_key: createIdempotencyKey(),
          expected_resource_version: context.resource_version,
          expected_catalog_release_id: context.catalog_release_id,
          confirmed: true,
        },
      );
      setDraft(null);
      await onApplied(result);
    } catch {
      setConflict(true);
    } finally {
      setApplying(false);
    }
  };

  return (
    <section className="rounded-lg border border-[#EBECF0] bg-black/[0.02] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-blue-500/[0.07] px-2.5 py-1 text-xs font-medium text-blue-500">
          {localize(`f048_permission.mode.${context.mode.toLowerCase()}`)}
        </span>
        {context.parent_type && context.parent_id && (
          <span className="text-xs text-[#818181]">
            {localize("f048_permission.mode.parent")}: {context.parent_type}:
            {context.parent_id}
          </span>
        )}
        <span className="text-xs text-[#818181]">
          {localize("f048_permission.mode.projection")}:{" "}
          {context.projection_state}
        </span>
        {canSwitch && !draft && (
          <Button
            type="button"
            color="default"
            variant="outlined"
            size="medium"
            className="ml-auto"
            disabled={creating}
            onClick={() => void handleCreateDraft()}
          >
            {creating && <Loader2 aria-hidden="true" className="animate-spin" />}
            {localize(
              `f048_permission.mode.switch_to_${targetMode.toLowerCase()}`,
            )}
          </Button>
        )}
      </div>

      {conflict && (
        <p
          className="mt-3 flex items-center gap-2 text-sm text-red-600"
          role="alert"
        >
          <AlertTriangle aria-hidden="true" className="size-4" />
          {localize("f048_permission.mode.conflict")}
        </p>
      )}

      {draft && (
        <div className="mt-3 border-t border-[#EBECF0] pt-3">
          <p className="text-sm font-medium text-[#212121]">
            {localize("f048_permission.mode.affected_assignees", {
              count: draft.affected_assignees,
            })}
          </p>
          <p className="mt-1 text-xs text-[#818181]">{draft.expires_at}</p>
          {expired && (
            <p className="mt-2 text-sm font-medium text-amber-700" role="alert">
              {localize("f048_permission.mode.expired")}
            </p>
          )}
          <div className="mt-3 flex justify-end gap-2">
            <Button
              type="button"
              color="default"
              variant="outlined"
              size="medium"
              disabled={applying}
              onClick={() => setDraft(null)}
            >
              {localize("f048_permission.mode.cancel")}
            </Button>
            <Button
              type="button"
              disabled={applying || expired}
              onClick={() => void handleApply()}
            >
              {applying && (
                <Loader2 aria-hidden="true" className="animate-spin" />
              )}
              {localize("f048_permission.mode.confirm")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
