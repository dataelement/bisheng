import { Button, StateView } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import type { Upload } from "./SpaceFileUploadPanel";
import { FILE_STATUSES, StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceUploadProgressProps {
  jobs: readonly Upload[];
  observed: ReadonlyMap<number, KnowledgeSpaceChild>;
  unavailable: boolean;
  onCancel: (job: Upload) => void;
  onRetry: (job: Upload) => void;
  onRefresh?: () => void;
}
const terminal = (status: number | null | undefined) =>
  status === 2 || status === 3 || status === 6 || status === 7;
const phaseLabels: Record<Upload["phase"], string> = {
  queued: "queuing",
  uploading: "importing",
  registering: "f118.upload_staged",
  registered: "f118.upload_registered",
  error: "fileLoadFailed",
  cancelled: "f118.upload_cancelled",
};

export function SpaceUploadProgress({
  jobs,
  observed,
  unavailable,
  onCancel,
  onRetry,
  onRefresh,
}: SpaceUploadProgressProps) {
  const { t } = useTranslation("knowledge");
  const renderStatus = (original: KnowledgeSpaceChild) => {
    const row = terminal(original.status) ? original : (observed.get(original.id) ?? original);
    const unknown = !FILE_STATUSES[row.status ?? -1] ||
      (!terminal(original.status) && unavailable && !observed.has(original.id));
    return unknown ? (
      <span className="text-caption text-text-3">{t("f118.upload_status_unavailable")}</span>
    ) : <StatusIndicator status={row.status!} remark={row.remark ?? undefined} />;
  };
  return (
    <section aria-label={t("f118.upload_tasks")} className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-border-base">
      <div className="flex min-h-11 shrink-0 items-center justify-between gap-3 bg-fill-1 px-4 py-2">
        <h2 className="flex items-center gap-2 text-body font-medium text-text-1">
          {t("f118.upload_tasks")}
          <span className="text-caption font-normal text-text-3">{jobs.length}</span>
        </h2>
        {unavailable && onRefresh && (
          <Button variant="text" onClick={onRefresh}>{t("retry")}</Button>
        )}
      </div>
      {jobs.some((job) => job.registrationStarted) && (
        <p className="shrink-0 px-4 py-2 text-caption text-text-3">{t("f118.upload_may_continue")}</p>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {!jobs.length ? (
          <StateView size="inline" title={t("f118.upload_tasks_empty")} className="h-full min-h-24" />
        ) : (
          <ul>
            {jobs.map((job) => {
              const name = job.folder?.name ?? job.file.name;
              const single = !job.folder && job.phase === "registered" && job.rows?.length === 1;
              return (
                <li key={job.id} className="space-y-2 px-4 py-3 even:bg-fill-1">
                  <div className="flex min-w-0 items-center gap-3">
                    {job.folder ? (
                      <Outlined.FolderClose className="size-8 shrink-0 text-text-2" aria-hidden="true" />
                    ) : (
                      <Outlined.File className="size-8 shrink-0 text-text-3" aria-hidden="true" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-body text-text-1" title={name}>{name}</p>
                      <p role="status" className={`mt-0.5 text-caption ${job.phase === "error" ? "text-danger" : "text-text-3"}`}>
                        {t(phaseLabels[job.phase])}
                      </p>
                    </div>
                    {single && <div className="shrink-0">{renderStatus(job.rows![0])}</div>}
                    {(job.phase === "queued" || job.phase === "uploading" || job.phase === "registering") && (
                      <Button variant="text" color="default" onClick={() => onCancel(job)}>{t("cancel")}</Button>
                    )}
                    {(job.phase === "error" || job.phase === "cancelled") && (
                      <Button variant="text" onClick={() => onRetry(job)}>{t("retry")}</Button>
                    )}
                  </div>
                  {job.phase === "registered" && !single && job.rows?.map((original, index) => (
                    <div key={`${original.id}:${index}`} className="ml-11 flex min-w-0 items-center justify-between gap-3 py-1">
                      <span className="min-w-0 truncate text-body-sm text-text-2" title={original.file_name}>{original.file_name}</span>
                      <div className="shrink-0">{renderStatus(original)}</div>
                    </div>
                  ))}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
