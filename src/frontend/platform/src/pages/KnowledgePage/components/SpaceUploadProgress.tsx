import { Button } from "@bisheng/ui";
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
}
const terminal = (status: number | null | undefined) =>
  status === 2 || status === 3 || status === 6 || status === 7;
export function SpaceUploadProgress({
  jobs,
  observed,
  unavailable,
  onCancel,
  onRetry,
}: SpaceUploadProgressProps) {
  const { t } = useTranslation("knowledge");
  return (
    <ul className="space-y-3">
      {jobs.map((job) => (
        <li key={job.id} className="space-y-2 rounded-md border p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate">
              {job.folder?.name ?? job.file.name}
            </span>
            {(job.phase === "queued" ||
              job.phase === "uploading" ||
              job.phase === "registering") && (
              <Button variant="text" onClick={() => onCancel(job)}>
                {t("cancel")}
              </Button>
            )}
            {(job.phase === "error" || job.phase === "cancelled") && (
              <Button variant="text" onClick={() => onRetry(job)}>
                {t("retry")}
              </Button>
            )}
          </div>
          <div role="status">
            {job.phase === "queued" && t("queuing")}
            {job.phase === "uploading" && t("importing")}
            {job.phase === "registering" && t("f118.upload_staged")}
            {job.phase === "registered" && t("f118.upload_registered")}
            {job.phase === "error" && t("fileLoadFailed")}
            {job.phase === "cancelled" && t("f118.upload_cancelled")}
          </div>
          {job.registrationStarted && (
            <p className="text-sm text-text-secondary">
              {t("f118.upload_may_continue")}
            </p>
          )}
          {job.phase === "registered" &&
            job.rows?.map((original, index) => {
              const row = terminal(original.status)
                ? original
                : (observed.get(original.id) ?? original);
              const unknown =
                !FILE_STATUSES[row.status ?? -1] ||
                (!terminal(original.status) &&
                  unavailable &&
                  !observed.has(original.id));
              return (
                <div
                  key={`${original.id}:${index}`}
                  className="flex items-center gap-3"
                >
                  <span className="truncate">{row.file_name}</span>
                  {unknown ? (
                    <span>{t("f118.upload_status_unavailable")}</span>
                  ) : (
                    <StatusIndicator
                      status={row.status!}
                      remark={row.remark ?? undefined}
                    />
                  )}
                </div>
              );
            })}
        </li>
      ))}
    </ul>
  );
}
