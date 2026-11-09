import { Button } from "@bisheng/ui";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import { useSpaceProcessingJobs } from "../hooks/useSpaceProcessingJobs";
import type { JobState, ItemState } from "~/api/knowledgeProcessing";

interface SpaceProcessingPanelProps {
  spaceId: string;
  canEdit: boolean;
  state?: number | null;
}
const states = new Set<string>([
  "accepted",
  "running",
  "succeeded",
  "partial_failed",
  "failed",
  "obsolete",
  "pending",
]);
export function SpaceProcessingPanel({ spaceId, canEdit, state }: SpaceProcessingPanelProps) {
  const localize = useLocalize();
  const progress = useSpaceProcessingJobs(spaceId, canEdit);
  const tr = (key: string, values?: Record<string, string | number>) =>
    localize(`com_knowledge.processing_jobs.${key}`, values);
  const status = (value: JobState | ItemState) =>
    tr(states.has(value) ? `state_${value}` : "unknown");
  const { job, items } = progress;
  const blocked = progress.retrying || progress.pending;
  return (
    <>
      {(state === 3 || state === 4 || progress.available) && (
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 px-4 py-2">
          {state === 3 && (
            <p role="status" className="text-body-sm text-text-2">
              {tr("rebuilding")}
            </p>
          )}
          {state === 4 && (
            <p role="status" className="text-body-sm text-danger">
              {tr("rebuild_failed")}
            </p>
          )}
          {progress.available && (
            <Button
              variant="text"
              onClick={() => {
                void progress.show();
              }}
            >
              {tr("title")}
            </Button>
          )}
        </div>
      )}
      <Dialog
        open={progress.open}
        onOpenChange={(open) => {
          if (!open) progress.close();
        }}
      >
        <DialogContent
          aria-describedby={undefined}
          onEscapeKeyDown={(event) => {
            if (blocked) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (blocked) event.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>{tr("title")}</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-3 overflow-y-auto text-body-sm text-text-1">
            {progress.loading && <p role="status">{tr("loading")}</p>}
            {progress.error && <p role="alert">{tr("load_failed")}</p>}
            {progress.pending && <p role="status">{tr("unknown_ack")}</p>}
            {progress.accepted && <p role="status">{tr("accepted_hint")}</p>}
            {progress.selected ? (
              job && (
                <>
                  <p>
                    {tr(`kind_${job.kind}`)} · {status(job.state)}
                  </p>
                  <p>
                    {tr("counts", {
                      0: job.total_count,
                      1: job.succeeded_count,
                      2: job.failed_count,
                      3: job.pending_count,
                    })}
                  </p>
                  {job.state === "accepted" && <p>{tr("accepted_hint")}</p>}
                  {job.hidden_item_count > 0 && <p>{tr("hidden", { 0: job.hidden_item_count })}</p>}
                  {job.error_code != null && <p>{tr("error_code", { 0: job.error_code })}</p>}
                  <ul className="space-y-2">
                    {items?.data.map((item, index) => (
                      <li key={item.id}>
                        {tr("item", { 0: (progress.itemPage - 1) * 20 + index + 1 })} ·{" "}
                        {status(item.state)}
                        {item.error_code != null && (
                          <span> · {tr("error_code", { 0: item.error_code })}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                  {items && (
                    <div className="flex justify-end gap-2">
                      <Button
                        size="small"
                        variant="text"
                        disabled={progress.itemPage === 1 || blocked}
                        onClick={() => progress.setItemPage(progress.itemPage - 1)}
                      >
                        {tr("previous")}
                      </Button>
                      <Button
                        size="small"
                        variant="text"
                        disabled={progress.itemPage * 20 >= items.total || blocked}
                        onClick={() => progress.setItemPage(progress.itemPage + 1)}
                      >
                        {tr("next")}
                      </Button>
                    </div>
                  )}
                </>
              )
            ) : (
              <>
                <ul className="space-y-2">
                  {progress.history?.map((entry) => (
                    <li key={entry.id}>
                      <Button variant="text" onClick={() => progress.select(entry)}>
                        {tr(`kind_${entry.kind}`)} · {status(entry.state)} · {entry.succeeded_count}
                        /{entry.total_count}
                      </Button>
                    </li>
                  ))}
                </ul>
                {progress.history?.length === 0 && !progress.loading && !progress.error && (
                  <p>{tr("empty")}</p>
                )}
                {!!progress.history && (
                  <div className="flex justify-end gap-2">
                    <Button
                      size="small"
                      variant="text"
                      disabled={progress.page === 1}
                      onClick={() => progress.setPage(progress.page - 1)}
                    >
                      {tr("previous")}
                    </Button>
                    <Button
                      size="small"
                      variant="text"
                      disabled={progress.page * 20 >= progress.total}
                      onClick={() => progress.setPage(progress.page + 1)}
                    >
                      {tr("next")}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
          <DialogFooter>
            {progress.selected && (
              <Button variant="outlined" disabled={blocked} onClick={progress.historyView}>
                {tr("back")}
              </Button>
            )}
            <Button
              variant="outlined"
              disabled={progress.retrying || progress.loading}
              onClick={() => {
                void progress.refresh();
              }}
            >
              {tr("refresh")}
            </Button>
            {(job?.retryable || progress.pending) && (
              <Button
                loading={progress.retrying}
                disabled={progress.loading || (!!progress.error && !progress.pending)}
                onClick={() => {
                  void progress.retry();
                }}
              >
                {tr(progress.pending ? "retry_request" : "retry_failed")}
              </Button>
            )}
            <Button variant="outlined" disabled={blocked} onClick={progress.close}>
              {localize("close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
