import { useState } from "react";
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
          {view.result && (
            <>
              <p>{tr("valid")}</p>
              <ul>
                {view.result.valid_items.map((item, index) => (
                  <li key={index}>{item.name || tr("unnamed")}</li>
                ))}
              </ul>
            </>
          )}
          {(!!view.result?.invalid_items.length || view.localInvalid.length > 0) && (
            <>
              <p>{tr("invalid")}</p>
              <ul>
                {view.result?.invalid_items.map((item, index) => (
                  <li key={index}>
                    {item.name ? `${item.name}: ` : ""}
                    {reason(item.reason)}
                  </li>
                ))}
                {view.localInvalid.map((item, index) => (
                  <li key={`local-${index}`}>
                    {item.name || tr("unnamed")}: {reason("unsupported")}
                  </li>
                ))}
              </ul>
            </>
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
              <p>{tr("results")}</p>
              <ul>
                {view.outcome.items.map((item, index) => (
                  <li key={index}>
                    {names.get(item.id) || tr("unnamed")}: {tr(`state_${item.state}`)}
                  </li>
                ))}
              </ul>
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
