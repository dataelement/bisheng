import { Button } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { getKnowledgeUploadFormats } from "@/components/bs-comp/knowledgeUploadComponent/DropZone";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";
import { knowledgeUploadsApi } from "@/controllers/API/knowledgeUploads";
import {
  knowledgeVersionsApi,
  type KnowledgeVersionsApi,
} from "@/controllers/API/knowledgeVersions";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { locationContext } from "@/contexts/locationContext";
import { StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceVersionUploadPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  documentId: number;
  api?: KnowledgeVersionsApi;
  onChanged: () => Promise<void>;
  onBusyChange: (busy: boolean) => void;
}
export function SpaceVersionUploadPanel({
  scope,
  spaceId,
  parentId,
  documentId,
  api = knowledgeVersionsApi,
  onChanged,
  onBusyChange,
}: SpaceVersionUploadPanelProps) {
  const { t } = useTranslation("knowledge");
  const { appConfig } = useContext(locationContext);
  const client = useQueryClient();
  const opening = useId(),
    input = useId();
  const lifetime = useRef<AbortController>();
  const writing = useRef(false),
    registered = useRef(false);
  const [busy, setBusy] = useState(false),
    [started, setStarted] = useState(false),
    [uncertain, setUncertain] = useState(false);
  const [row, setRow] = useState<KnowledgeSpaceChild | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => {
      controller.abort();
      onBusyChange(false);
    };
  }, [onBusyChange]);
  const handleUpload = async (file: File) => {
    const controller = lifetime.current;
    if (
      !controller ||
      controller.signal.aborted ||
      writing.current ||
      registered.current
    )
      return;
    const suffix = file.name.split(".").pop()?.toLowerCase() ?? "";
    const media = [
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
    ].includes(suffix);
    const maxMB = media
      ? (appConfig.uploadMediaMaxSize ?? 1024)
      : (appConfig.uploadFileMaxSize ?? 50);
    if (
      !getKnowledgeUploadFormats(
        !!appConfig.enableEtl4lm,
        !!appConfig.enableMediaUpload,
      ).some((ext) => ext.toLowerCase() === `.${suffix}`) ||
      file.size > maxMB * 1024 * 1024 ||
      (media && !appConfig.enableMediaUpload)
    ) {
      showApiError(new Error(t("versions.upload_invalid")));
      return;
    }
    writing.current = true;
    setBusy(true);
    onBusyChange(true);
    setStarted(true);
    try {
      const staged = await knowledgeUploadsApi.uploadSpaceFile(
        spaceId,
        file,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if (!staged.preview_upload_ref)
        throw new Error(t("versions.upload_unconfirmed"));
      // Registration is attempted once. A lost ACK must never create another file.
      registered.current = true;
      const rows = await knowledgeUploadsApi.registerSpaceFiles(
        spaceId,
        {
          file_path: [staged.file_path],
          preview_upload_refs: [staged.preview_upload_ref],
          parent_id: parentId,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if (
        rows.length !== 1 ||
        rows[0].knowledge_id !== spaceId ||
        rows[0].file_type !== 1 ||
        !Number.isSafeInteger(rows[0].id) ||
        rows[0].id <= 0
      )
        throw new Error(t("versions.upload_unconfirmed"));
      setRow(rows[0]);
      await client.invalidateQueries({
        queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "children"],
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        setUncertain(true);
        showApiError(error);
      }
    } finally {
      writing.current = false;
      if (!controller.signal.aborted) {
        setBusy(false);
        onBusyChange(false);
      }
    }
  };
  const status = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "new-version-status",
      opening,
      parentId,
      row?.id,
    ],
    enabled: !!row && ![2, 3, 6, 7].includes(row.status ?? -1),
    queryFn: async ({ signal }) => {
      const result = await knowledgeSpaceApi.listChildren(spaceId, {
        parent_id: parentId,
        file_ids: [row!.id],
        page_size: 1,
      });
      if (signal?.aborted) throw new Error("Version upload tracking retired");
      const actual = result.data.find(
        (item) =>
          item.id === row!.id &&
          item.knowledge_id === spaceId &&
          item.file_type === 1,
      );
      if (!actual || result.has_more)
        throw new Error(t("versions.upload_unconfirmed"));
      return actual;
    },
    retry: false,
    cacheTime: 0,
    refetchInterval: (actual, query) =>
      query.state.status === "error" ||
      (actual && [2, 3, 6, 7].includes(actual.status ?? -1))
        ? false
        : 2000,
  });
  useEffect(() => {
    if (status.error) showApiError(status.error);
  }, [status.error]);
  const actual = status.isError ? undefined : (status.data ?? row);
  const handleLink = () => {
    const controller = lifetime.current;
    if (
      !controller ||
      controller.signal.aborted ||
      !actual ||
      actual.status !== 2 ||
      writing.current ||
      uncertain
    )
      return;
    let attempted = false;
    bsConfirm({
      title: t("versions.new_version"),
      desc: t("versions.confirm_uploaded", { name: actual.file_name }),
      signal: controller.signal,
      onOk: async (close) => {
        if (controller.signal.aborted || writing.current || attempted) return;
        attempted = true;
        writing.current = true;
        setBusy(true);
        onBusyChange(true);
        try {
          await api.linkSpaceFileVersion(
            actual.id,
            documentId,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          close();
          await onChanged();
        } catch (error) {
          if (!controller.signal.aborted) {
            setUncertain(true);
            close();
            showApiError(error);
          }
        } finally {
          writing.current = false;
          if (!controller.signal.aborted) {
            setBusy(false);
            onBusyChange(false);
          }
        }
      },
    });
  };
  return (
    <section className="space-y-3 rounded-md border p-3">
      <h3 className="font-medium">{t("versions.new_version")}</h3>
      <p className="text-sm text-muted-foreground">
        {t("versions.upload_hint")}
      </p>
      <label htmlFor={input} className="text-sm">
        {t("versions.choose_file")}
      </label>
      <input
        id={input}
        type="file"
        disabled={busy || started}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleUpload(file);
        }}
      />
      {busy && <p role="status">{t("loading")}</p>}
      {uncertain && (
        <p role="alert" className="text-sm">
          {t("versions.uncertain")}
        </p>
      )}
      {row && (
        <div className="space-y-2">
          <p className="break-words">{row.file_name}</p>
          {typeof actual?.status === "number" ? (
            <StatusIndicator status={actual.status} />
          ) : (
            <p>{t("versions.upload_unconfirmed")}</p>
          )}
          {status.isError && (
            <Button variant="outlined" onClick={() => void status.refetch()}>
              {t("retry")}
            </Button>
          )}
          <Button
            disabled={busy || uncertain || actual?.status !== 2}
            onClick={handleLink}
          >
            {t("versions.confirm_new_version")}
          </Button>
        </div>
      )}
    </section>
  );
}
