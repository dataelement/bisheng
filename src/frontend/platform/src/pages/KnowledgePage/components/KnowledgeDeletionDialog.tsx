import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { useState } from "react";
import { KnowledgeDeletionItems, KnowledgeReferenceTables } from "@bisheng/knowledge";
import { Button, Checkbox } from "@bisheng/ui";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/bs-ui/dialog";
import { useTranslation } from "react-i18next";
import type { useKnowledgeDeletion } from "../hooks/useKnowledgeDeletion";
interface KnowledgeDeletionDialogProps {
  operation: ReturnType<typeof useKnowledgeDeletion>;
}
export function KnowledgeDeletionDialog({ operation }: KnowledgeDeletionDialogProps) {
  const { t } = useTranslation("knowledge");
  const tr = (key: string) => t(`deletion.${key}`);
  const { view } = operation;
  const [consent, setConsent] = useState<{ plan?: string; skip: boolean; danger: boolean }>({
    skip: false,
    danger: false,
  });
  if (!view) return null;
  const plan = view.result?.plan_digest;
  const skip = consent.plan === plan && consent.skip;
  const danger = consent.plan === plan && consent.danger;
  const impact = view.result?.impact ?? view.inspection;
  const complete = view.result?.check_complete ?? view.inspection?.check_complete;
  const referenceComplete = view.result?.impact.reference_check_complete ?? view.inspection?.check_complete;
  const locked = view.busy || view.dispatched;
  const needsSkip = !!view.result?.requires_skip_confirmation;
  const executable =
    !!view.result?.can_execute &&
    complete &&
    !view.stale &&
    (!needsSkip || skip) &&
    (!view.force || danger);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) operation.cancel();
      }}
    >
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-2xl grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto] px-4 sm:px-5"
        aria-describedby={undefined}
        onPointerDownOutside={(event) => {
          if (locked) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (locked) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {tr(
              view.readonly
                ? "references"
                : view.command.kind === "clear"
                  ? "clear"
                  : view.command.kind === "delete"
                    ? "delete_space"
                    : "delete_items",
            )}
          </DialogTitle>
        </DialogHeader>
        <div className="min-h-0 min-w-0 max-h-[60vh] overflow-y-auto space-y-4 text-body-sm">
          {view.busy && <LoadingState label={tr("checking")} className="min-h-32" />}
          {(view.error || view.code) && (
            <p role="alert">
              {view.code === 10999 && view.reason === "source_space_move_input_required"
                ? tr("source_tasks_block_delete")
                : view.code === 10994
                ? tr("hints_unavailable")
                : view.stale
                  ? tr("changed")
                  : view.error || tr("failed")}
            </p>
          )}
          {complete === false && <p role="alert">{tr("failed")}</p>}
          {referenceComplete === false && <p role="alert">{tr("hints_unavailable")}</p>}
          {referenceComplete === true && <p>{tr("hints_notice")}</p>}
          {!view.readonly && view.result && (
            <>
              <p>{tr("irreversible")}</p>
              <p>
                {tr("item_count")} {view.result.impact.file_count}
              </p>
              <KnowledgeDeletionItems
                validItems={view.result.valid_items}
                invalidItems={view.result.invalid_items}
                translate={tr}
              />
              {needsSkip && (
                <Checkbox
                  disabled={locked}
                  checked={skip}
                  onCheckedChange={(checked) =>
                    setConsent({ plan, skip: checked === true, danger })
                  }
                  label={tr("skip_confirm")}
                />
              )}
              {view.force && (
                <div className="space-y-2 text-danger">
                  <p>{tr("force_warning")}</p>
                  <Checkbox
                    disabled={locked}
                    checked={danger}
                    onCheckedChange={(checked) =>
                      setConsent({ plan, skip, danger: checked === true })
                    }
                    label={tr("force_confirm")}
                  />
                </div>
              )}
            </>
          )}
          <KnowledgeReferenceTables
            impact={referenceComplete === false ? undefined : impact}
            slotCounts={view.readonly ? view.inspection?.slot_counts : undefined}
            page={view.page}
            readonly={view.readonly}
            deletingSpace={view.command.kind === "delete"}
            translate={tr}
          />
          {view.page?.has_more && (
            <Button
              variant="text"
              disabled={view.busy || view.stale}
              onClick={() => {
                void operation.more();
              }}
            >
              {tr("more")}
            </Button>
          )}
          {view.dispatched && (
            <div role="status" className="space-y-2">
              <p>{tr("pending")}</p>
              {view.status && (
                <>
                  <p>
                    {tr("state")}{" "}
                    {tr(
                      ["pending", "running", "succeeded"].includes(view.status.state)
                        ? `state_${view.status.state}`
                        : "state_pending",
                    )}
                  </p>
                  {view.status.business_phase && (
                    <p>
                      {tr("phase")}{" "}
                      {tr(
                        view.status.business_phase === "finalized"
                          ? "phase_finalized"
                          : "phase_prepared",
                      )}
                    </p>
                  )}
                  <p>
                    {tr("completed_steps")} {view.status.completed_steps?.length ?? 0}/4
                  </p>
                </>
              )}
            </div>
          )}
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          {!view.readonly && (
            <Button color="default" variant="outlined" disabled={locked} onClick={() => operation.cancel()}>
              {tr("close")}
            </Button>
          )}
          {!view.dispatched && (
            <Button variant="outlined" disabled={view.busy} onClick={operation.refresh}>
              {tr("review")}
            </Button>
          )}
          {view.dispatched && (
            <Button
              variant="outlined"
              disabled={view.busy}
              onClick={() => {
                void operation.status();
              }}
            >
              {tr("status")}
            </Button>
          )}
          {!view.readonly && (
            <Button
              color="danger"
              disabled={view.busy || !executable}
              onClick={() => {
                void operation.confirm(skip, danger);
              }}
            >
              {tr(view.dispatched ? "retry_same" : view.force ? "force_delete" : "confirm")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
