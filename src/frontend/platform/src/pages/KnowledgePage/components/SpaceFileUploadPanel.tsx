import { Button, toast } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import {
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import DropZone from "@/components/bs-comp/knowledgeUploadComponent/DropZone";
import { locationContext } from "@/contexts/locationContext";
import {
  knowledgeUploadsApi,
  type SpaceUploadFile,
} from "@/controllers/API/knowledgeUploads";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { FILE_STATUSES, StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceFileUploadPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
}
type Phase =
  "queued" | "uploading" | "registering" | "registered" | "error" | "cancelled";
type Upload = {
  id: number;
  file: File;
  phase: Phase;
  staged?: SpaceUploadFile;
  rows?: KnowledgeSpaceChild[];
  controller?: AbortController;
  token?: symbol;
  registrationStarted: boolean;
};
type Epoch = {
  id: number;
  prefix: readonly unknown[];
  parentId: number | null;
  retired: boolean;
  jobs: Map<number, Upload>;
  active: Set<symbol>;
  next: number;
};
const terminal = (status: number | null | undefined) =>
  status === 2 || status === 3 || status === 6 || status === 7;
const validId = (id: number) => Number.isSafeInteger(id) && id > 0;
const media = new Set([
  "mp3",
  "wav",
  "m4a",
  "aac",
  "flac",
  "ogg",
  "mp4",
  "mov",
  "avi",
  "mkv",
  "webm",
]);

export function SpaceFileUploadPanel({
  scope,
  spaceId,
  parentId,
}: SpaceFileUploadPanelProps) {
  const { t } = useTranslation("knowledge");
  const { appConfig } = useContext(locationContext);
  const instance = useId();
  const sequence = useRef(0);
  const { identityKey, tenantId, managementTenantId, view } = scope;
  const epoch = useMemo<Epoch>(
    () => ({
      id: ++sequence.current,
      prefix: knowledgeQueryKeys.space(
        { identityKey, tenantId, managementTenantId, view },
        spaceId,
      ),
      parentId,
      retired: false,
      jobs: new Map(),
      active: new Set(),
      next: 0,
    }),
    [identityKey, tenantId, managementTenantId, view, spaceId, parentId],
  );
  const current = useRef<Epoch | null>(epoch);
  current.current = epoch;
  const [snapshot, setSnapshot] = useState<{ epoch: Epoch; jobs: Upload[] }>({
    epoch,
    jobs: [],
  });
  const jobs = useMemo(
    () => (snapshot.epoch === epoch ? snapshot.jobs : []),
    [epoch, snapshot],
  );
  const sync = useCallback(() => {
    if (current.current === epoch && !epoch.retired)
      setSnapshot({ epoch, jobs: [...epoch.jobs.values()] });
  }, [epoch]);
  useEffect(() => {
    epoch.retired = false;
    return () => {
      epoch.retired = true;
      if (current.current === epoch) current.current = null;
      for (const job of epoch.jobs.values()) job.controller?.abort();
    };
  }, [epoch]);

  const run = useCallback(
    async (job: Upload) => {
      if (current.current !== epoch || epoch.retired || job.phase !== "queued")
        return;
      const controller = new AbortController(),
        token = Symbol();
      job.controller = controller;
      job.token = token;
      epoch.active.add(token);
      const live = () =>
        current.current === epoch &&
        !epoch.retired &&
        job.token === token &&
        !controller.signal.aborted;
      try {
        if (!job.staged) {
          job.phase = "uploading";
          sync();
          const staged = await knowledgeUploadsApi.uploadSpaceFile(
            spaceId,
            job.file,
            controller.signal,
          );
          if (!live()) return;
          job.staged = staged;
        }
        job.phase = "registering";
        job.registrationStarted = true;
        sync();
        const rows = await knowledgeUploadsApi.registerSpaceFiles(
          spaceId,
          { file_path: [job.staged.file_path], parent_id: parentId },
          controller.signal,
        );
        if (!live()) return;
        job.rows = rows;
        job.phase = rows.length ? "registered" : "error";
      } catch (error) {
        if (live()) {
          job.phase = "error";
          showApiError(error);
        }
      } finally {
        epoch.active.delete(token);
        sync();
      }
    },
    [epoch, parentId, spaceId, sync],
  );
  useEffect(() => {
    for (const job of jobs) {
      if (epoch.active.size >= 6) break;
      if (job.phase === "queued") void run(job);
    }
  }, [epoch, jobs, run]);

  const ids = [
    ...new Set(
      jobs.flatMap((job) =>
        job.phase === "registered"
          ? (job.rows ?? [])
              .filter((row) => validId(row.id) && !terminal(row.status))
              .map((row) => row.id)
          : [],
      ),
    ),
  ].sort((a, b) => a - b);
  const status = useQuery<KnowledgeSpaceChild[]>({
    queryKey: [
      ...epoch.prefix,
      "upload-status",
      instance,
      epoch.id,
      epoch.parentId,
      ids,
    ],
    enabled: ids.length > 0,
    retry: false,
    cacheTime: 0,
    queryFn: async () => {
      const rows: KnowledgeSpaceChild[] = [];
      for (let start = 0; start < ids.length; start += 100) {
        const selected = ids.slice(start, start + 100),
          seen = new Set<string>();
        let cursor: string | undefined;
        for (let pages = 0; ; pages++) {
          if (current.current !== epoch || epoch.retired)
            throw new Error("Upload tracking retired");
          if (pages >= 100)
            throw new Error("Upload status cursor exceeded its bounded scan");
          const result = await knowledgeSpaceApi.listChildren(spaceId, {
            parent_id: parentId,
            file_ids: selected,
            page_size: 100,
            ...(cursor === undefined ? {} : { cursor }),
          });
          if (current.current !== epoch || epoch.retired)
            throw new Error("Upload tracking retired");
          rows.push(
            ...result.data.filter(
              (row) =>
                selected.includes(row.id) && row.knowledge_id === spaceId,
            ),
          );
          if (!result.has_more) break;
          if (!result.next_cursor || seen.has(result.next_cursor))
            throw new Error("Upload status cursor did not progress");
          cursor = result.next_cursor;
          seen.add(cursor);
        }
      }
      return rows;
    },
    refetchInterval: (rows, query) =>
      query.state.status === "error" ||
      (rows &&
        ids.every((id) => terminal(rows.find((row) => row.id === id)?.status)))
        ? false
        : 1000,
  });
  useEffect(() => {
    if (status.error && current.current === epoch && !epoch.retired)
      showApiError(status.error);
  }, [epoch, status.error]);
  const observed = new Map(status.data?.map((row) => [row.id, row]));
  const unavailable =
    ids.length > 0 &&
    (status.isError ||
      (status.isSuccess && ids.some((id) => !observed.has(id))));
  const handleDrop = (files: File[]) => {
    if (current.current !== epoch || epoch.retired) return;
    for (const file of files) {
      const isMedia = media.has(
        file.name.split(".").pop()?.toLowerCase() ?? "",
      );
      const limit = isMedia
        ? (appConfig.uploadMediaMaxSize ?? 1024)
        : (appConfig.uploadFileMaxSize ?? 50);
      if (file.size > limit * 1024 * 1024) {
        toast.show({
          type: "error",
          message: t("code.sizeExceedsLimit", { size: `${limit}MB` }),
        });
        continue;
      }
      const id = ++epoch.next;
      epoch.jobs.set(id, {
        id,
        file,
        phase: "queued",
        registrationStarted: false,
      });
    }
    sync();
  };
  const handleCancel = (job: Upload) => {
    job.controller?.abort();
    if (job.token) epoch.active.delete(job.token);
    job.token = undefined;
    job.phase = "cancelled";
    sync();
  };
  return (
    <section aria-label={t("uploadFile")} className="space-y-4">
      <DropZone onDrop={handleDrop} />
      <ul className="space-y-3">
        {jobs.map((job) => (
          <li key={job.id} className="space-y-2 rounded-md border p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="truncate">{job.file.name}</span>
              {(job.phase === "queued" ||
                job.phase === "uploading" ||
                job.phase === "registering") && (
                <Button variant="text" onClick={() => handleCancel(job)}>
                  {t("cancel")}
                </Button>
              )}
              {(job.phase === "error" || job.phase === "cancelled") && (
                <Button
                  variant="text"
                  onClick={() => {
                    job.phase = "queued";
                    sync();
                  }}
                >
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
      {unavailable && (
        <Button
          variant="outlined"
          onClick={() => {
            void status.refetch();
          }}
        >
          {t("retry")}
        </Button>
      )}
    </section>
  );
}
