import { Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { SpaceCopyTask } from "@/controllers/API/knowledgeCopy";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";

interface SpaceCopyStatusProps {
  scope: KnowledgeQueryScope;
  task: SpaceCopyTask;
  onCompleted: () => void;
  compact?: boolean;
}

function SpaceCopyDisclosure({
  scope,
  task,
  onCompleted,
}: Omit<SpaceCopyStatusProps, "compact">) {
  const { t } = useTranslation("knowledge");
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const summaryId = useId();
  const failed = task.phase === "failed";
  const partial = task.job_state === "partial_failed";
  const failureLabel = partial
    ? "space_copy_ui.partial_failed"
    : task.job_state === "obsolete"
      ? "f118.processing_state_obsolete"
      : "space_copy_ui.failed";

  return (
    <div className="mx-4 my-3 shrink-0 rounded-lg border border-border-base">
      <SpaceProcessingProgress
        scope={scope}
        spaceId={task.id}
        jobId={task.job_id}
        kind="space_copy"
        onCompleted={onCompleted}
        copyDisclosure={{
          open,
          phase: task.phase,
          render: (retryAction, details, preparing) => (
            <>
              <div
                className={`relative isolate flex min-h-11 items-center justify-between gap-3 bg-fill-1 px-3 py-2 text-body text-text-1 ${open && !preparing ? "rounded-t-lg" : "rounded-lg"} ${preparing ? "" : "hover:bg-fill-2"}`}
              >
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <span id={summaryId} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                    {preparing ? (
                      <span role="status">{t("space_copy_ui.phase_preparing")}</span>
                    ) : failed ? (
                      <>
                        <Tag size="small" dot color={partial ? "warning" : "danger"}>
                          {t(failureLabel)}
                        </Tag>
                        <span className="text-body-sm tabular-nums text-text-2">
                          {t("space_copy_ui.failure_counts", {
                            completed: task.succeeded_count,
                            failed: task.failed_count,
                          })}
                        </span>
                      </>
                    ) : (
                      <span>
                        {t(`space_copy_ui.phase_${task.phase}`, {
                          completed: task.succeeded_count,
                          total: task.total_count,
                        })}
                      </span>
                    )}
                  </span>
                  {retryAction && <span className="relative z-10 inline-flex">{retryAction}</span>}
                </div>
                {!preparing && (
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={detailsId}
                    aria-describedby={summaryId}
                    className={`inline-flex shrink-0 items-center gap-1.5 text-body-sm text-blue-500 after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-offset-2 focus-visible:after:outline-blue-500 ${open ? "after:rounded-t-lg" : "after:rounded-lg"}`}
                    onClick={() => setOpen((current) => !current)}
                  >
                    {t(open ? "sidebar.collapse" : "space_copy_ui.view_details")}
                    <Outlined.Down className={open ? "size-4 rotate-180" : "size-4"} aria-hidden />
                  </button>
                )}
              </div>
              <div
                id={detailsId}
                role="region"
                aria-label={t("space_copy_ui.tasks")}
                tabIndex={0}
                hidden={!open || preparing}
                className="max-h-[min(42dvh,24rem)] overflow-y-auto overscroll-contain border-t border-border-base p-3 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-500"
              >
                {details}
              </div>
            </>
          ),
        }}
      />
    </div>
  );
}

export function SpaceCopyStatus({
  scope,
  task,
  onCompleted,
  compact = false,
}: SpaceCopyStatusProps) {
  const { t } = useTranslation("knowledge");
  if (compact) {
    return (
      <SpaceCopyDisclosure
        key={task.job_id}
        scope={scope}
        task={task}
        onCompleted={onCompleted}
      />
    );
  }
  const failed = task.phase === "failed";
  return (
    <section
      className={failed ? "flex min-h-full flex-col gap-4 p-4" : "space-y-4 p-4"}
      aria-live="polite"
    >
      <h1 className="break-words text-h4 text-text-1">{task.name}</h1>
      {!failed && (
        <>
          <p role="status">
            {t(`space_copy_ui.phase_${task.phase}`, {
              completed: task.succeeded_count,
              total: task.total_count,
            })}
          </p>
          <p className="text-body-sm text-text-3">
            {t("space_copy_ui.background_notice")}
          </p>
        </>
      )}
      {(task.phase === "copying" || failed) && (
        <SpaceProcessingProgress
          scope={scope}
          spaceId={task.id}
          jobId={task.job_id}
          kind="space_copy"
          onCompleted={onCompleted}
          showCopyFailurePage={failed}
        />
      )}
    </section>
  );
}
