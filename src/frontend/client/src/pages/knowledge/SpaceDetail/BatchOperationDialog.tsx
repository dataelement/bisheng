import { useState } from "react";
import { BATCH_OPERATION_DIALOG_CLASS, KnowledgeDialogTable } from "@bisheng/knowledge";
import { Button, Checkbox } from "@bisheng/ui";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "~/components/ui";
import type { useKnowledgeBatch } from "../hooks/useKnowledgeBatch";
import { useLocalize } from "~/hooks";
interface BatchOperationDialogProps {
  operation: ReturnType<typeof useKnowledgeBatch>;
}
export function BatchOperationDialog({ operation }: BatchOperationDialogProps) {
  const localize = useLocalize();
  const tr = (key: string) => localize(`com_knowledge.batch.${key}`);
  const { view } = operation;
  const [consent, setConsent] = useState<string | null>(null);
  if (!view) return null;
  const plan = view.result?.plan_digest,
    skip = !!plan && consent === plan;
  const needsSkip = !!view.result?.requires_skip_confirmation || view.localInvalid.length > 0;
  const pending = view.outcome?.items.some((item) => item.state === "pending_dispatch");
  const blockedClose = view.busy || (view.dispatched && (!view.outcome || pending));
  const names = new Map(
    [...(view.result?.valid_items ?? []), ...(view.result?.invalid_items ?? [])].map((item) => [
      item.id,
      item.name,
    ]),
  );
  const reason = (value: string) =>
    tr(
      ["no_permission", "processing", "unsupported", "not_found", "type_mismatch"].includes(value)
        ? `reason_${value}`
        : "reason_unsupported",
    );
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) operation.close();
      }}
    >
      <DialogContent
        className={BATCH_OPERATION_DIALOG_CLASS}
        aria-describedby={undefined}
        onPointerDownOutside={(event) => {
          if (blockedClose) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (blockedClose) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{tr(view.command.operation)}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 max-h-[60vh] overflow-y-auto text-body-sm">
          {view.busy && <p role="status">{tr("checking")}</p>}
          {view.error && <p role="alert">{view.stale ? tr("changed") : view.error}</p>}
          {!!view.result?.valid_items.length && (
            <KnowledgeDialogTable
              caption={tr("valid")}
              columns={[{ label: tr("column_name") }]}
              rows={view.result.valid_items.map((item) => ({
                key: `${item.type}-${item.id}`,
                cells: [item.name || tr("unnamed")],
              }))}
            />
          )}
          {(!!view.result?.invalid_items.length || view.localInvalid.length > 0) && (
            <KnowledgeDialogTable
              caption={tr("invalid")}
              columns={[{ label: tr("column_name") }, { label: tr("column_reason") }]}
              rows={[
                ...(view.result?.invalid_items ?? []).map((item, index) => ({
                  key: index,
                  cells: [item.name || tr("unnamed"), reason(item.reason)],
                })),
                ...view.localInvalid.map((item, index) => ({
                  key: `local-${index}`,
                  cells: [item.name || tr("unnamed"), reason("unsupported")],
                })),
              ]}
            />
          )}
          {needsSkip && !view.outcome && (
            <Checkbox
              disabled={view.busy || view.dispatched}
              label={tr("skip")}
              checked={skip}
              onCheckedChange={(checked) => setConsent(checked === true ? (plan ?? null) : null)}
            />
          )}
          {view.outcome && (
            <>
              {!!view.outcome.items.length && (
                <KnowledgeDialogTable
                  caption={tr("results")}
                  columns={[{ label: tr("column_name") }, { label: tr("column_status") }]}
                  rows={view.outcome.items.map((item) => ({
                    key: `${item.type}-${item.id}`,
                    cells: [names.get(item.id) || tr("unnamed"), tr(`state_${item.state}`)],
                  }))}
                />
              )}
              {view.command.operation === "retry" && <p>{tr("retry_receipt")}</p>}
              {pending && <p role="status">{tr("unknown_ack")}</p>}
              {view.outcome.url && (
                <a
                  className="text-primary underline"
                  href={view.outcome.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {tr("download_result")}
                </a>
              )}
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outlined" disabled={blockedClose} onClick={operation.close}>
            {tr(view.outcome ? "done" : "cancel")}
          </Button>
          {!view.dispatched && (
            <Button
              variant="outlined"
              disabled={view.busy || !view.command.items.length}
              onClick={operation.review}
            >
              {tr("review")}
            </Button>
          )}
          {(!view.outcome ||
            pending ||
            (view.command.operation === "download" && view.outcome.items.some((item) => item.state === "failed"))) && (
            <Button
              disabled={
                view.busy ||
                !view.result?.can_execute ||
                !view.result.check_complete ||
                (needsSkip && !skip)
              }
              onClick={() => {
                void operation.confirm(skip);
              }}
            >
              {tr(view.dispatched ? "retry_same" : "confirm")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
