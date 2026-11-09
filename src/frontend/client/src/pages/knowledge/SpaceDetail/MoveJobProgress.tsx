import { Button } from "@bisheng/ui";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import type { useMoveJobProgress } from "../hooks/useMoveJobProgress";

interface MoveJobProgressProps {
  progress: ReturnType<typeof useMoveJobProgress>;
}

export function MoveJobProgress({ progress }: MoveJobProgressProps) {
  const localize = useLocalize();
  const { job, items, error, page } = progress;
  return (
    <Dialog open={progress.open} onOpenChange={progress.setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {localize("com_knowledge.move_progress_title")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-body text-text-1">
          {progress.confirmation ? (
            <div>
              <p role="status">
                {localize("com_knowledge.move_resume_confirmation")}
              </p>
              {error && (
                <p role="alert">
                  {localize("com_knowledge.move_progress_error")}
                </p>
              )}
            </div>
          ) : error ? (
            <p role="alert">{localize("com_knowledge.move_progress_error")}</p>
          ) : job ? (
            <>
              <p>{localize(`com_knowledge.move_state_${job.state}`)}</p>
              <p>
                {localize("com_knowledge.move_progress_counts", {
                  0: job.succeeded_count,
                  1: job.total_count,
                  2: job.failed_count,
                })}
              </p>
              {job.hidden_item_count > 0 && (
                <p className="text-caption text-text-3">
                  {localize("com_knowledge.move_hidden_items", {
                    0: job.hidden_item_count,
                  })}
                </p>
              )}
              <ul className="max-h-64 space-y-1 overflow-y-auto">
                {items?.data.map((item) => (
                  <li key={item.id} className="text-body-sm">
                    {localize("com_knowledge.move_item_progress", {
                      0: item.file_id,
                      1: localize(`com_knowledge.move_state_${item.state}`),
                    })}
                  </li>
                ))}
              </ul>
              <div className="flex justify-end gap-2">
                <Button
                  size="small"
                  variant="text"
                  disabled={page === 1}
                  onClick={() => progress.setPage(page - 1)}
                >
                  {localize("com_knowledge.move_previous_page")}
                </Button>
                <Button
                  size="small"
                  variant="text"
                  disabled={!items || page * 20 >= items.total}
                  onClick={() => progress.setPage(page + 1)}
                >
                  {localize("com_knowledge.move_next_page")}
                </Button>
              </div>
            </>
          ) : (
            <div>
              {progress.history?.data.map((entry) => (
                <Button
                  key={entry.id}
                  variant="text"
                  onClick={() => void progress.select(entry.id)}
                >
                  {localize(`com_knowledge.move_state_${entry.state}`)} ·{" "}
                  {entry.succeeded_count}/{entry.total_count}
                </Button>
              ))}
              <div className="flex justify-end gap-2">
                <Button
                  size="small"
                  variant="text"
                  disabled={page === 1}
                  onClick={() => progress.setPage(page - 1)}
                >
                  {localize("com_knowledge.move_previous_page")}
                </Button>
                <Button
                  size="small"
                  variant="text"
                  disabled={
                    !progress.history || page * 20 >= progress.history.total
                  }
                  onClick={() => progress.setPage(page + 1)}
                >
                  {localize("com_knowledge.move_next_page")}
                </Button>
              </div>
            </div>
          )}
        </div>
        <DialogFooter>
          {progress.confirmation && (
            <Button
              loading={progress.retrying}
              onClick={() => void progress.resumeConfirmation()}
            >
              {localize("com_knowledge.move_resume")}
            </Button>
          )}
          {error && (
            <Button
              variant="outlined"
              loading={progress.loading}
              onClick={() => void progress.refresh()}
            >
              {localize("com_knowledge.move_refresh")}
            </Button>
          )}
          {job?.retryable && (
            <Button
              loading={progress.retrying}
              onClick={() => void progress.retry()}
            >
              {localize("com_knowledge.move_retry_failed")}
            </Button>
          )}
          <Button variant="outlined" onClick={() => progress.setOpen(false)}>
            {localize("close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
