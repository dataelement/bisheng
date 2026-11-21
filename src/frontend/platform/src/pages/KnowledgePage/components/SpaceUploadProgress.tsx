import { KnowledgeFileTypeIcon } from "@bisheng/file-viewers/knowledge-artwork";
import { Button, StateView } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import type { Upload } from "./SpaceFileUploadPanel";
import { FILE_STATUSES, StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceUploadProgressProps {
  jobs: readonly Upload[];
  observed: ReadonlyMap<number, KnowledgeSpaceChild>;
  unavailable: boolean;
  scrollRows?: boolean;
  onCancel: (job: Upload) => void;
  onRetry: (job: Upload) => void;
  onRefresh?: () => void;
  onRemove?: (job: Upload) => void;
  onOpenExisting?: (parentId: number | null) => void;
  onOverwrite?: (row: KnowledgeSpaceChild) => Promise<void> | void;
}
export function duplicateHold(row: KnowledgeSpaceChild): { parentId: number | null | undefined; location: string } | null {
  if (row.status !== 3) return null;
  const text = row.remark?.trim() ?? "";
  if (!text.startsWith("{")) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const value = parsed as Record<string, unknown>;
  if ("status_code" in value || typeof value.new_name !== "string" || typeof value.old_name !== "string") return null;
  const parts = (row.file_level_path ?? "").split("/").filter(Boolean);
  const numeric = parts.every((part) => /^[1-9][0-9]*$/.test(part) && Number.isSafeInteger(Number(part)));
  const parentId = !parts.length ? null : numeric ? Number(parts[parts.length - 1]) : undefined;
  return { parentId, location: row.old_file_level_path?.replace(/^\/+/, "") ?? "" };
}
const terminal = (status: number | null | undefined) =>
  status === 2 || status === 3 || status === 6 || status === 7;
const phaseLabels: Record<Upload["phase"], string> = {
  queued: "queuing",
  staged: "f118.upload_staged",
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
  scrollRows = true,
  onCancel,
  onRetry,
  onRefresh,
  onRemove,
  onOpenExisting,
  onOverwrite,
}: SpaceUploadProgressProps) {
  const { t } = useTranslation("knowledge");
  const [handled, setHandled] = useState<ReadonlySet<number>>(() => new Set());
  const renderDuplicate = (row: KnowledgeSpaceChild) => {
    const hold = duplicateHold(row);
    if (!hold) return null;
    const place = hold.location || t("f118.upload_duplicate_root");
    return (
      <div className="space-y-2">
        <p className="text-caption text-text-2">{t("f118.upload_duplicate")}</p>
        <p className="text-caption text-text-2">{t("f118.upload_duplicate_location", { path: place })}</p>
        {!handled.has(row.id) && (
          <div className="flex flex-wrap gap-2">
            {onOpenExisting && hold.parentId !== undefined && (
              <Button variant="outlined" onClick={() => onOpenExisting(hold.parentId ?? null)}>{t("f118.upload_open_existing")}</Button>
            )}
            {onOverwrite && (
              <Button onClick={() => {
                void Promise.resolve(onOverwrite(row))
                  .then(() => setHandled((current) => new Set(current).add(row.id)))
                  .catch(() => undefined);
              }}>{t("override")}</Button>
            )}
            <Button variant="text" onClick={() => setHandled((current) => new Set(current).add(row.id))}>{t("keepOriginal")}</Button>
          </div>
        )}
      </div>
    );
  };
  const currentRow = (original: KnowledgeSpaceChild) =>
    terminal(original.status) ? original : (observed.get(original.id) ?? original);
  const renderStatus = (original: KnowledgeSpaceChild) => {
    const row = currentRow(original);
    if (duplicateHold(row)) return null;
    const unknown = !FILE_STATUSES[row.status ?? -1] ||
      (!terminal(original.status) && unavailable && !observed.has(original.id));
    return unknown ? (
      <span className="text-caption text-text-3">{t("f118.upload_status_unavailable")}</span>
    ) : <StatusIndicator status={row.status!} remark={row.remark ?? undefined} />;
  };
  return (
    <section
      aria-label={t("f118.upload_tasks")}
      className={`flex min-w-0 flex-col rounded-lg border border-border-base ${scrollRows ? "min-h-0 flex-1 overflow-hidden" : "overflow-clip"}`}
    >
      <div className="flex min-h-11 shrink-0 items-center justify-between gap-3 bg-fill-1 px-4 py-2">
        <h2 className="flex items-center gap-2 text-body font-medium text-text-1">
          {t("f118.upload_tasks")}
          <span className="text-caption font-normal text-text-3">{jobs.length}</span>
        </h2>
        {unavailable && onRefresh && (
          <Button variant="text" onClick={onRefresh}>{t("retry")}</Button>
        )}
      </div>
      <div className={scrollRows ? "min-h-0 flex-1 overflow-y-auto" : undefined}>
        {!jobs.length ? (
          <StateView size="inline" title={t("f118.upload_tasks_empty")} className="h-full min-h-24" />
        ) : (
          <ul>
            {jobs.map((job) => {
              const name = job.folder?.name ?? job.file.name;
              const single = !job.folder && job.phase === "registered" && job.rows?.length === 1;
              const canCancel = job.phase === "queued" || job.phase === "uploading" || job.phase === "registering";
              return (
                <li key={job.id} className="space-y-2 px-4 py-2 even:bg-fill-1">
                  <div className="flex min-w-0 items-center gap-3">
                    {job.folder ? (
                      <Outlined.FolderClose className="size-8 shrink-0 text-text-2" aria-hidden="true" />
                    ) : (
                      <KnowledgeFileTypeIcon name={job.file.name} className="size-8 shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-body text-text-1" title={name}>{name}</p>
                      <p role="status" className={`mt-0.5 text-caption ${job.phase === "error" ? "text-danger" : "text-text-3"}`}>
                        {t(phaseLabels[job.phase])}
                      </p>
                    </div>
                    {single && renderStatus(job.rows![0]) && <div className="shrink-0">{renderStatus(job.rows![0])}</div>}
                    {canCancel && (
                      <Button variant="text" color="default" onClick={() => onCancel(job)}>{t("cancel")}</Button>
                    )}
                    {!job.registrationStarted && (job.phase === "error" || job.phase === "cancelled") && (
                      <Button variant="text" onClick={() => onRetry(job)}>{t("retry")}</Button>
                    )}
                    {onRemove && !job.registrationStarted && !canCancel && <Button variant="text" onClick={() => onRemove(job)}>{t("delete")}</Button>}
                  </div>
                  {single && duplicateHold(currentRow(job.rows![0])) && (
                    <div className="ml-11">{renderDuplicate(currentRow(job.rows![0]))}</div>
                  )}
                  {job.phase === "registered" && !single && job.rows?.map((original, index) => (
                    <div key={`${original.id}:${index}`} className="ml-11 space-y-2 py-1">
                      <div className="flex min-w-0 items-center justify-between gap-3">
                        <span className="min-w-0 truncate text-body-sm text-text-2" title={original.file_name}>{original.file_name}</span>
                        <div className="shrink-0">{renderStatus(original)}</div>
                      </div>
                      {renderDuplicate(currentRow(original))}
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
