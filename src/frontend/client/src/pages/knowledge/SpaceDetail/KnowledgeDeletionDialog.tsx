import { useState } from "react";
import { Button, Checkbox } from "@bisheng/ui";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "~/components/ui";
import { useLocalize } from "~/hooks";
import type { useKnowledgeDeletion } from "../hooks/useKnowledgeDeletion";
interface KnowledgeDeletionDialogProps {
  operation: ReturnType<typeof useKnowledgeDeletion>;
}
export function KnowledgeDeletionDialog({ operation }: KnowledgeDeletionDialogProps) {
  const localize = useLocalize();
  const tr = (key: string) => localize(`com_knowledge.deletion.${key}`);
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
  const hasReferences =
    Object.values(impact?.source_counts ?? {}).some((count) => count > 0) ||
    Object.values(impact?.restricted_counts ?? {}).some((count) => count > 0) ||
    !!view.page?.data.length || !!view.page?.has_more;
  const locked = view.busy || view.dispatched;
  const needsSkip = !!view.result?.requires_skip_confirmation;
  const executable =
    !!view.result?.can_execute &&
    complete &&
    !view.stale &&
    (!needsSkip || skip) &&
    (!view.force || danger);
  const sourceKinds = new Set([
    "workflow_version",
    "assistant",
    "hosted_app_version",
    "channel_sync",
    "knowledge",
    "model_default",
  ]);
  const kindLabel = (kind: string) => tr(sourceKinds.has(kind) ? `source_${kind}` : "source_other");
  const reasonLabel = (reason: string) =>
    tr(
      ["not_found", "type_mismatch", "referenced", "processing", "no_permission"].includes(reason)
        ? `reason_${reason}`
        : "reason_other",
    );
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) operation.cancel();
      }}
    >
      <DialogContent
        className="max-w-2xl"
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
        <div className="max-h-[60vh] overflow-y-auto space-y-4 text-body-sm">
          {view.busy && <p role="status">{tr("checking")}</p>}
          {(view.error || view.code) && (
            <p role="alert">
              {view.code === 10994
                ? tr("unavailable")
                : view.stale
                  ? tr("changed")
                  : view.error || tr("failed")}
            </p>
          )}
          {complete === false && <p role="alert">{tr("unavailable")}</p>}
          {!view.readonly && view.result && (
            <>
              <p>{tr("irreversible")}</p>
              <p>
                {tr("item_count")} {view.result.impact.file_count}
              </p>
              {!!view.result.valid_items.length && (
                <div>
                  <p>{tr("valid_items")}</p>
                  <ul>
                    {view.result.valid_items.map((item, index) => (
                      <li key={index}>{item.name || tr("unnamed")}</li>
                    ))}
                  </ul>
                </div>
              )}
              {!!view.result.invalid_items.length && (
                <div>
                  <p>{tr("invalid_items")}</p>
                  <ul>
                    {view.result.invalid_items.map((item, index) => (
                      <li key={index}>
                        {item.name ? `${item.name}: ` : ""}
                        {reasonLabel(item.reason)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
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
          {hasReferences && impact && (
            <>
              <div>
                <p>{tr("source_counts")}</p>
                {Object.entries(impact.source_counts).map(([kind, count]) => (
                  <p key={kind}>
                    {kindLabel(kind)}: {count}
                  </p>
                ))}
              </div>
              {Object.values(impact.restricted_counts).some((count) => count > 0) && <div>
                <p>{tr("restricted")}</p>
                {Object.entries(impact.restricted_counts).map(([kind, count]) => (
                  <p key={kind}>
                    {kindLabel(kind)}: {count}
                  </p>
                ))}
              </div>}
              {view.readonly && view.inspection && (
                <div>
                  <p>{tr("slot_counts")}</p>
                  {Object.entries(view.inspection.slot_counts).map(([kind, count]) => (
                    <p key={kind}>
                      {kindLabel(kind)}: {count}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
          {!!view.page?.data.length && (
            <ul className="space-y-2">
              {view.page.data.map((row, index) => {
                const { disclosure } = row;
                const entry = disclosure.entry;
                const safe =
                  entry &&
                  (/^https?:\/\//i.test(entry) ||
                    (entry.startsWith("/") && !entry.startsWith("//")));
                return (
                  <li key={index}>
                    <p>
                      {kindLabel(disclosure.source.source_type)}:{" "}
                      {safe ? (
                        <a
                          href={entry}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary underline"
                        >
                          {disclosure.name || tr("unnamed")}
                        </a>
                      ) : (
                        disclosure.name || tr("unnamed")
                      )}
                    </p>
                    {disclosure.version_label && <p>{disclosure.version_label}</p>}
                    <p>
                      {tr("matched_slots")} {row.matched_slot_count}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
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
        <DialogFooter>
          <Button variant="outlined" disabled={locked} onClick={() => operation.cancel()}>
            {tr("close")}
          </Button>
          {!view.dispatched && (
            <Button variant="outlined" disabled={view.busy} onClick={operation.refresh}>
              {tr("review")}
            </Button>
          )}
          {!view.readonly &&
            !view.force &&
            !view.dispatched &&
            view.command.kind === "delete" &&
            view.result?.check_complete &&
            !view.result.can_execute &&
            view.code !== 10994 &&
            !view.stale && (
              <Button color="danger" variant="outlined" onClick={operation.force}>
                {tr("force_review")}
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
