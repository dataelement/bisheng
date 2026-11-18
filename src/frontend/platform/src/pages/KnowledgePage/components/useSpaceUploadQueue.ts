import { toast } from "@bisheng/ui";
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
import { getKnowledgeUploadFormats } from "@/components/bs-comp/knowledgeUploadComponent/DropZone";
import { locationContext } from "@/contexts/locationContext";
import {
  knowledgeUploadsApi,
  type SpaceUploadFile,
} from "@/controllers/API/knowledgeUploads";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceChild,
  type ProcessingOverrides,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import {
  knowledgeUploadPreviewApi,
  type UploadContext,
  type UploadPreview,
} from "@/controllers/API/knowledgeUploadPreview";
interface SpaceFileUploadPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
}
type Phase =
  | "queued"
  | "uploading"
  | "staged"
  | "registering"
  | "registered"
  | "error"
  | "cancelled";
export type Upload = {
  id: number;
  file: File;
  phase: Phase;
  staged?: SpaceUploadFile;
  rows?: KnowledgeSpaceChild[];
  controller?: AbortController;
  token?: symbol;
  registrationStarted: boolean;
  overrides?: ProcessingOverrides;
  context?: UploadContext;
  register?: boolean;
  folder?: {
    name: string;
    entries: { file: File; relativePath: string; staged?: SpaceUploadFile }[];
  };
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

const uploadRelativePath = (file: File) =>
  (
    file.webkitRelativePath ||
    ("path" in file && typeof file.path === "string" ? file.path : "")
  )
    .replace(/^\.\//, "")
    .replace(/^\/+/, "");

export function useSpaceUploadQueue({
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
        if (job.folder) {
          job.phase = "uploading";
          sync();
          for (const entry of job.folder.entries) {
            if (!entry.staged) {
              const staged = await knowledgeUploadPreviewApi.stageFile(
                spaceId,
                parentId,
                entry.file,
                controller.signal,
              );
              if (!live()) return;
              if (!staged.upload_id) throw new Error("Missing upload receipt");
              entry.staged = staged;
            }
          }
          if (!job.register) {
            job.phase = "staged";
            return;
          }
          job.phase = "registering";
          job.registrationStarted = true;
          sync();
          const rows = await knowledgeUploadsApi.registerSpaceFolder(
            spaceId,
            {
              parent_id: parentId,
              upload_context: job.context,
              items: job.folder.entries.map((entry) => ({
                file_path: entry.staged!.file_path,
                relative_path: entry.relativePath,
                size: entry.file.size,
              })),
              ...(job.overrides === undefined
                ? {}
                : { overrides: structuredClone(job.overrides) }),
            },
            controller.signal,
          );
          if (!live()) return;
          job.rows = rows;
          job.phase = rows.length ? "registered" : "error";
          return;
        }
        if (!job.staged) {
          job.phase = "uploading";
          sync();
          const staged = await knowledgeUploadPreviewApi.stageFile(
            spaceId,
            parentId,
            job.file,
            controller.signal,
          );
          if (!live()) return;
          if (!staged.upload_id) throw new Error("Missing upload receipt");
          job.staged = staged;
        }
        if (!job.register) {
          job.phase = "staged";
          return;
        }
        job.phase = "registering";
        job.registrationStarted = true;
        sync();
        const rows = await knowledgeUploadsApi.registerSpaceFiles(
          spaceId,
          {
            file_path: [job.staged.file_path],
            upload_context: job.context,
            parent_id: parentId,
            ...(job.overrides === undefined
              ? {}
              : { overrides: structuredClone(job.overrides) }),
          },
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

  const targets = [
    ...new Map(
      jobs
        .flatMap((job) =>
          job.phase === "registered"
            ? (job.rows ?? [])
                .filter((row) => validId(row.id) && !terminal(row.status))
                .map((row) => {
                  let parent: number | null | undefined = parentId;
                  if (job.folder) {
                    const parts = row.file_level_path
                      ?.split("/")
                      .filter(Boolean);
                    parent =
                      parts?.length &&
                      parts.every(
                        (part) =>
                          /^[1-9][0-9]*$/.test(part) && validId(Number(part)),
                      )
                        ? Number(parts[parts.length - 1])
                        : undefined;
                  }
                  return [row.id, { id: row.id, parent }] as const;
                })
            : [],
        )
        .map(([id, target]) => [id, target] as const),
    ).values(),
  ].sort((a, b) => a.id - b.id);
  const ids = targets.map((target) => target.id);
  const status = useQuery<KnowledgeSpaceChild[]>({
    queryKey: [
      ...epoch.prefix,
      "upload-status",
      instance,
      epoch.id,
      epoch.parentId,
      targets,
    ],
    enabled: ids.length > 0,
    retry: false,
    cacheTime: 0,
    queryFn: async () => {
      const rows: KnowledgeSpaceChild[] = [];
      const groups = new Map<number | null, number[]>();
      for (const target of targets)
        if (target.parent !== undefined) {
          const selected = groups.get(target.parent) ?? [];
          selected.push(target.id);
          groups.set(target.parent, selected);
        }
      for (const [actualParent, scopedIds] of groups)
        for (let start = 0; start < scopedIds.length; start += 100) {
          const selected = scopedIds.slice(start, start + 100),
            seen = new Set<string>();
          let cursor: string | undefined;
          for (let pages = 0; ; pages++) {
            if (current.current !== epoch || epoch.retired)
              throw new Error("Upload tracking retired");
            if (pages >= 100)
              throw new Error("Upload status cursor exceeded its bounded scan");
            const result = await knowledgeSpaceApi.listChildren(spaceId, {
              parent_id: actualParent,
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
    if (files.some((file) => uploadRelativePath(file).includes("/"))) {
      handleFolder(files);
      return;
    }
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
          message: t("code.sizeExceedsLimit", { ns: "bs", size: limit }),
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
  const handleFolder = (picked: File[]) => {
    if (current.current !== epoch || epoch.retired || !picked.length) return;
    const root = picked
      .map(uploadRelativePath)
      .find((path) => path.includes("/"))
      ?.split("/")[0];
    if (!root || root.startsWith(".")) return;
    if (picked.length > 1000) {
      toast.show({ type: "warning", message: t("f118.folder_upload_limit") });
      return;
    }
    const formats = new Set(
      getKnowledgeUploadFormats(
        appConfig.enableEtl4lm,
        !!appConfig.enableMediaUpload,
      ).map((value) => value.toLowerCase().slice(1)),
    );
    let rejected = 0;
    const entries = picked.flatMap((file) => {
      const relativePath = uploadRelativePath(file) || file.name;
      if (
        !relativePath ||
        relativePath.split("/").some((part) => part.startsWith("."))
      )
        return [];
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      const limit = media.has(extension)
        ? (appConfig.uploadMediaMaxSize ?? 1024)
        : (appConfig.uploadFileMaxSize ?? 50);
      if (!formats.has(extension) || file.size > limit * 1024 * 1024) {
        rejected++;
        return [];
      }
      return [{ file, relativePath }];
    });
    if (rejected)
      toast.show({
        type: "warning",
        message: t("f118.folder_upload_skipped", { count: rejected }),
      });
    if (!entries.length) {
      toast.show({ type: "warning", message: t("f118.folder_upload_empty") });
      return;
    }
    const id = ++epoch.next;
    epoch.jobs.set(id, {
      id,
      file: entries[0].file,
      phase: "queued",
      registrationStarted: false,
      folder: { name: root, entries },
    });
    sync();
  };
  const handleCancel = (job: Upload) => {
    job.controller?.abort();
    if (job.token) epoch.active.delete(job.token);
    job.token = undefined;
    job.phase = "cancelled";
    sync();
  };
  const files = useMemo(
    () =>
      jobs.flatMap((job) =>
        job.folder
          ? job.folder.entries
              .filter((entry) => entry.staged)
              .map((entry) => ({
                job,
                file: entry.file,
                staged: entry.staged!,
              }))
          : job.staged
            ? [{ job, file: job.file, staged: job.staged }]
            : [],
      ),
    [jobs],
  );
  const commit = (
    mode: "previewed" | "direct",
    rules: (filePath: string) => ProcessingOverrides,
    previews: Record<string, { value: UploadPreview; fingerprint: string }>,
  ) => {
    if (
      current.current !== epoch ||
      epoch.retired ||
      !jobs.length ||
      jobs.some((job) => job.phase !== "staged")
    )
      return false;
    for (const job of jobs) {
      const selected = files.filter((item) => item.job === job);
      job.context = {
        mode,
        items: selected.map((item) => {
          const preview = previews[item.staged.upload_id!]?.value;
          return {
            upload_id: item.staged.upload_id!,
            file_path: item.staged.file_path,
            overrides: structuredClone(rules(item.staged.file_path)),
            ...(mode === "previewed" && preview
              ? {
                  preview_id: preview.preview_id,
                  expected_revision: preview.revision,
                }
              : {}),
          };
        }),
      };
      job.overrides = structuredClone(rules(selected[0].staged.file_path));
      job.register = true;
      job.phase = "queued";
    }
    sync();
    return true;
  };
  return {
    jobs,
    files,
    observed,
    unavailable,
    handleDrop,
    handleFolder,
    handleCancel,
    commit,
    retry: (job: Upload) => {
      if (job.registrationStarted) return;
      job.phase = "queued";
      sync();
    },
    remove: (job: Upload) => {
      if (job.registrationStarted) return;
      handleCancel(job);
      epoch.jobs.delete(job.id);
      sync();
    },
    retryStatus: () => status.refetch(),
  };
}
