import { Button, Select } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  knowledgeUploadPreviewApi,
  type UploadPreview,
} from "@/controllers/API/knowledgeUploadPreview";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import useKnowledgeStore from "../useKnowledgeStore";
import PreviewFile from "./PreviewFile";
import PreviewParagraph from "./PreviewParagraph";
import {
  buildMediaUploadPreviewData,
  isMediaUploadSuffix,
} from "./RichPreviewFile";
import { wizardOverrides, type WizardStrategy } from "./uploadWizardRules";

export type PreviewBook = Record<
  string,
  { value: UploadPreview; fingerprint: string }
>;
interface SpaceUploadPreviewProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  strategy: WizardStrategy;
  book: PreviewBook;
  onPreview: (id: string, record: PreviewBook[string]) => void;
  onBusy: (busy: boolean) => void;
  previewCount?: number;
  editable?: boolean;
}
const wait = (signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Retired preview", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, 1000);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
export function SpaceUploadPreview(props: SpaceUploadPreviewProps) {
  const { t } = useTranslation("knowledge");
  const labels = useSelectLabels();
  const [selected, setSelected] = useState(
    props.strategy.rules.fileList[0]?.id ?? "",
  );
  const file = props.strategy.rules.fileList.find(
    (item) => item.id === selected,
  );
  if (!file) return <p role="status">{t("f118.directory_empty")}</p>;
  return (
    <section className="flex h-full min-h-0 flex-col gap-3">
      <Select
        {...labels}
        aria-label={t("selectFile")}
        className="ml-auto w-72"
        options={props.strategy.rules.fileList.map((item) => ({
          value: item.id,
          label: item.fileName,
        }))}
        value={file.id}
        onChange={(value) => {
          if (value) setSelected(String(value));
        }}
      />
      <ValidatedPane key={file.id} {...props} file={file} />
    </section>
  );
}
function ValidatedPane(
  props: SpaceUploadPreviewProps & {
    file: WizardStrategy["rules"]["fileList"][number];
  },
) {
  const { t } = useTranslation("knowledge");
  let fingerprint: string;
  try {
    fingerprint = JSON.stringify(
      wizardOverrides(props.strategy, props.file.filePath),
    );
  } catch {
    return <p role="alert">{t("f118.invalid_defaults")}</p>;
  }
  return (
    <PreviewPane
      key={`${props.file.id}:${fingerprint}:${props.previewCount ?? 0}`}
      {...props}
    />
  );
}
function safeBbox(value: unknown): string {
  if (typeof value !== "string") return "";
  try {
    return Array.isArray(JSON.parse(value)?.chunk_bboxes) ? value : "";
  } catch {
    return "";
  }
}
function PreviewPane({
  scope,
  spaceId,
  strategy,
  book,
  onPreview,
  onBusy,
  previewCount = 0,
  editable = false,
  file,
}: SpaceUploadPreviewProps & {
  file: WizardStrategy["rules"]["fileList"][number];
}) {
  const { t } = useTranslation("knowledge");
  const instance = useId();
  const writeController = useRef<AbortController | null>(null);
  const alive = useRef(true),
    locked = useRef(false);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<{
    run: () => Promise<UploadPreview>;
  } | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const overrides = wizardOverrides(strategy, file.filePath);
  const fingerprint = JSON.stringify(overrides);
  const cached = book[file.id];
  const query = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "upload-preview",
      instance,
      file.id,
      fingerprint,
      previewCount,
    ],
    initialData:
      previewCount === 0 &&
      cached?.fingerprint === fingerprint &&
      cached.value.status === "completed"
        ? cached.value
        : undefined,
    queryFn: async ({ signal }) => {
      const preview_id =
        previewCount === 0 &&
        cached?.fingerprint === fingerprint &&
        cached.value.status === "processing"
          ? cached.value.preview_id
          : (
              await knowledgeUploadPreviewApi.start(
                spaceId,
                file.id,
                overrides,
                signal,
              )
            ).preview_id;
      if (signal?.aborted)
        throw new DOMException("Retired preview", "AbortError");
      onPreview(file.id, {
        fingerprint,
        value: { preview_id, revision: 0, status: "processing" },
      });
      const deadline = Date.now() + 10 * 60 * 1000;
      for (;;) {
        if (Date.now() > deadline) throw new Error(t("previewFailed"));
        const value = await knowledgeUploadPreviewApi.read(
          spaceId,
          file.id,
          preview_id,
          signal,
        );
        if (signal?.aborted)
          throw new DOMException("Retired preview", "AbortError");
        if (value.status === "error") throw new Error(t("previewFailed"));
        if (value.status === "completed") return value;
        await wait(signal);
      }
    },
    retry: false,
    cacheTime: 0,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });
  const [edited, setEdited] = useState<UploadPreview>();
  const value = edited ?? query.data;
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    writeController.current = controller;
    const store = useKnowledgeStore.getState();
    store.setSelectedChunkIndex(-1);
    store.setSelectedBbox([]);
    return () => {
      alive.current = false;
      controller.abort();
      onBusy(false);
    };
  }, [onBusy]);
  const selectedChunk = useKnowledgeStore((state) => state.selectedChunkIndex);
  useEffect(() => {
    useKnowledgeStore.getState().setSelectedBbox([]);
  }, [selectedChunk]);
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  useEffect(() => {
    onBusy(query.isFetching || query.isError || saving || Boolean(failed));
  }, [query.isFetching, query.isError, saving, failed, onBusy]);
  useEffect(() => {
    if (value?.status === "completed")
      onPreview(file.id, { value, fingerprint });
  }, [value, file.id, fingerprint, onPreview]);
  const data = value?.data;
  const chunks = useMemo(
    () =>
      (data?.chunks ?? []).map((chunk) => ({
        text: drafts[chunk.metadata.chunk_index] ?? chunk.text,
        chunkIndex: chunk.metadata.chunk_index,
        bbox: safeBbox(chunk.metadata.bbox),
      })),
    [data, drafts],
  );
  const write = async (operation: () => Promise<UploadPreview>) => {
    if (!alive.current || locked.current || !editable) return;
    locked.current = true;
    setSaving(true);
    onBusy(true);
    try {
      const next = await operation();
      if (!alive.current) return;
      setEdited(next);
      setDrafts({});
      setFailed(null);
    } catch (error) {
      if (alive.current) {
        setFailed({ run: operation });
        showApiError(error);
      }
    } finally {
      locked.current = false;
      if (alive.current) setSaving(false);
    }
  };
  if (query.isError)
    return (
      <div role="alert">
        <p>{t("previewFailed")}</p>
        <Button
          onClick={() => {
            void query.refetch();
          }}
        >
          {t("retry")}
        </Button>
      </div>
    );
  if (!data || !value) return <p role="status">{t("loading")}</p>;
  const previewFile = {
    ...file,
    id: file.id,
    name: file.fileName,
    fileType: data.parse_type,
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {failed && (
        <div role="alert">
          <p>{t("detail.save_failed")}</p>
          <Button
            disabled={saving}
            onClick={() => {
              void write(failed.run);
            }}
          >
            {t("retry")}
          </Button>
          <Button
            disabled={saving}
            onClick={() => {
              onBusy(true);
              setEdited(undefined);
              setDrafts({});
              setFailed(null);
              void query.refetch();
            }}
          >
            {t("repreviewSegmentation")}
          </Button>
        </div>
      )}
      <div className="flex min-h-0 flex-1 gap-3 bg-background-main">
        {editable && (
          <PreviewFile
            file={previewFile}
            rawFiles={[previewFile]}
            step={3}
            edit={!saving && !failed}
            chunks={chunks}
            setChunks={() => undefined}
            partitions={data.partitions ?? {}}
            urlState={{ load: query.isFetching, url: data.file_url }}
            previewUrl={data.file_url}
            previewData={
              isMediaUploadSuffix(file.suffix)
                ? buildMediaUploadPreviewData(
                    file.filePath,
                    data.file_url,
                    file.suffix,
                  )
                : undefined
            }
          />
        )}
        <div className="min-h-0 min-w-0 flex-1">
          <PreviewParagraph
            key={`${value.preview_id}:${value.revision}`}
            fileId={file.id}
            fileSuffix={file.suffix}
            previewCount={chunks.length}
            chunks={chunks}
            immediateSave
            className="h-full min-h-0"
            loading={query.isFetching || saving}
            edit={editable && !saving && !failed}
            canDelete={editable && !saving && !failed}
            onChange={(index: number, text: string) => {
              if (!alive.current || locked.current || !editable) return;
              const chunk = data.chunks.find(
                (item) => item.metadata.chunk_index === index,
              );
              if (!chunk) return;
              const selection = useKnowledgeStore.getState();
              const bbox =
                selection.selectedChunkIndex === index &&
                selection.selectedBbox.length
                  ? JSON.stringify({ chunk_bboxes: selection.selectedBbox })
                  : (chunk.metadata.bbox ?? "");
              setDrafts((previous) => ({ ...previous, [index]: text }));
              void write(() =>
                knowledgeUploadPreviewApi.edit(
                  spaceId,
                  file.id,
                  value.preview_id,
                  index,
                  value.revision,
                  text,
                  bbox,
                  writeController.current?.signal,
                ),
              );
            }}
            onDel={(index: number) =>
              bsConfirm({
                desc: t("f118.index_delete_chunk"),
                signal: writeController.current?.signal,
                onOk: () =>
                  write(() =>
                    knowledgeUploadPreviewApi.delete(
                      spaceId,
                      file.id,
                      value.preview_id,
                      index,
                      value.revision,
                      writeController.current?.signal,
                    ),
                  ),
              })
            }
          />
        </div>
      </div>
    </div>
  );
}
