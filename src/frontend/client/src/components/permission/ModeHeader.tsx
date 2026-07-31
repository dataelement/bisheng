import { AlertTriangle, Loader2, ShieldCheck } from "lucide-react";
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
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui";
import { useLocalize } from "~/hooks";

interface ModeHeaderProps {
  resourceType: ResourceType;
  resourceId: string;
  context: ResourcePermissionContext;
  onApplied: (result: ApplyPermissionModeDraftResult) => void | Promise<void>;
  now?: Date;
}

const MODES: ResourcePermissionMode[] = ["INHERIT", "CUSTOM"];

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
  now = new Date(),
}: ModeHeaderProps) {
  const localize = useLocalize();
  const [draft, setDraft] = useState<PermissionModeDraft | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [conflict, setConflict] = useState(false);
  const hasParent = Boolean(context.parent_type && context.parent_id);
  const expired =
    draft !== null && new Date(draft.expires_at).getTime() <= now.getTime();
  const canSwitch =
    hasParent && context.can_manage_permission && !creating && !applying;

  if (!hasParent) return null;

  const handleCreateDraft = async (targetMode: ResourcePermissionMode) => {
    if (!canSwitch || targetMode === context.mode) return;
    setCreating(true);
    setConflict(false);
    try {
      const result = await createResourcePermissionModeDraft(
        resourceType,
        resourceId,
        {
          target_mode: targetMode,
          expected_resource_version: context.resource_version,
          expected_catalog_release_id: context.catalog_release_id,
        },
      );
      setDraft(result);
      setConfirmOpen(true);
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
      setConfirmOpen(false);
      setDraft(null);
      await onApplied(result);
    } catch {
      setConflict(true);
    } finally {
      setApplying(false);
    }
  };

  return (
    <>
      <section
        className="border-y border-[#EBECF0] bg-black/[0.02] px-5 py-3"
        data-testid="permission-mode-switch"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-medium text-[#212121]">
            {localize("f048_permission.mode.label")}
          </span>
          <div
            className="inline-flex rounded-md border border-[#D9DDE7] bg-white p-0.5"
            role="group"
            aria-label={localize("f048_permission.mode.label")}
          >
            {MODES.map((mode) => {
              const active = context.mode === mode;
              const modeKey = mode.toLowerCase();
              return (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={active}
                  aria-label={
                    active
                      ? localize(`f048_permission.mode.${modeKey}`)
                      : localize(
                          `f048_permission.mode.switch_to_${modeKey}`,
                        )
                  }
                  disabled={!active && !canSwitch}
                  className="min-h-8 rounded px-3 text-sm text-[#4E5969] transition-colors hover:bg-black/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:bg-blue-500/[0.07] aria-pressed:font-medium aria-pressed:text-blue-500"
                  onClick={() => void handleCreateDraft(mode)}
                >
                  {creating && !active ? (
                    <Loader2
                      aria-hidden="true"
                      className="mr-1 inline size-3.5 animate-spin"
                    />
                  ) : null}
                  {localize(`f048_permission.mode.${modeKey}`)}
                </button>
              );
            })}
          </div>
          <p className="flex min-w-0 items-center gap-1.5 text-sm text-[#4E5969]">
            <ShieldCheck aria-hidden="true" className="size-4 shrink-0" />
            {localize(
              context.mode === "INHERIT"
                ? "f048_permission.mode.inherit_description"
                : "f048_permission.mode.custom_description",
            )}
          </p>
        </div>
        <p className="mt-2 text-xs leading-5 text-[#86909C] sm:pl-[88px]">
          {localize(
            context.mode === "INHERIT"
              ? "f048_permission.mode.inherit_helper"
              : "f048_permission.mode.custom_helper",
          )}
        </p>
        {conflict && !confirmOpen && (
          <p
            className="mt-2 flex items-center gap-2 text-sm text-red-600"
            role="alert"
          >
            <AlertTriangle aria-hidden="true" className="size-4" />
            {localize("f048_permission.mode.conflict")}
          </p>
        )}
      </section>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {localize("f048_permission.mode.confirm_title")}
            </DialogTitle>
            <DialogDescription>
              {localize("f048_permission.mode.confirm_description")}
            </DialogDescription>
          </DialogHeader>
          {draft && (
            <div className="space-y-3">
              <div className="rounded-lg border border-[#EBECF0] bg-black/[0.02] p-3">
                <p className="text-xs text-[#818181]">
                  {localize("f048_permission.mode.affected_assignees", {
                    count: draft.affected_assignees,
                  })}
                </p>
                <p
                  data-testid="mode-affected-assignees"
                  className="mt-1 text-xl font-semibold tabular-nums"
                >
                  {draft.affected_assignees}
                </p>
              </div>
              {expired && (
                <p
                  className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-medium text-amber-900"
                  role="alert"
                >
                  {localize("f048_permission.mode.expired")}
                </p>
              )}
              {conflict && (
                <p className="text-sm text-red-600" role="alert">
                  {localize("f048_permission.mode.conflict")}
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              type="button"
              color="default"
              variant="outlined"
              size="medium"
              disabled={applying}
              onClick={() => setConfirmOpen(false)}
            >
              {localize("f048_permission.mode.cancel")}
            </Button>
            <Button
              type="button"
              disabled={!draft || expired || applying}
              onClick={() => void handleApply()}
            >
              {localize("f048_permission.mode.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
