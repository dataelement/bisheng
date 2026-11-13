import { Button, Pagination, SearchInput, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileIcon, type FileType } from "@/components/bs-icons/file";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import PreviewFile from "./PreviewFile";
import PreviewParagraph from "./PreviewParagraph";
import { SpaceProcessingDialog } from "./SpaceProcessingDialog";
import { SpaceFileMetadataDialog } from "./SpaceFileMetadataDialog";
import { useSpaceFileDetail } from "./useSpaceFileDetail";
interface SpaceFileDetailProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  initialFile?: KnowledgeSpaceChild;
  onBack: () => void;
}
function safeBbox(value: string | null | undefined): string {
  if (!value) return "";
  try {
    return Array.isArray(JSON.parse(value)?.chunk_bboxes) ? value : "";
  } catch {
    return "";
  }
}
export function SpaceFileDetail({ scope, spaceId, fileId, initialFile, onBack }: SpaceFileDetailProps) {
  const { t } = useTranslation("knowledge");
  const locale = usePaginationLocale();
  const model = useSpaceFileDetail(scope, spaceId, fileId);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [processingOpen, setProcessingOpen] = useState(false);
  const raw = model.info.data ?? initialFile;
  const name = model.preview.isSuccess ? (raw?.file_name ?? t("detail.file_title", { id: fileId })) : "";
  const file = useMemo(
    () => ({
      ...raw,
      id: fileId,
      name,
      fileName: name,
      fileType: raw?.parse_type ?? "",
      suffix: raw?.file_name?.includes(".")
        ? (raw.file_name.split(".").pop()?.toLowerCase() ?? "txt")
        : "txt",
    }),
    [raw, fileId, name],
  );
  const chunks = useMemo(
    () =>
      (model.chunks.data?.data ?? []).map((row) => ({
        text: model.drafts[row.metadata.chunk_index] ?? row.text ?? "",
        chunkIndex: row.metadata.chunk_index,
        bbox: safeBbox(row.metadata.bbox),
      })),
    [model.chunks.data, model.drafts],
  );
  const handleDelete = (index: number) =>
    bsConfirm({
      title: t("f118.index_delete_chunk"),
      desc: t("f118.index_delete_chunk"),
      onOk: () => model.handleDelete(index),
    });
  return (
    <section
      className="flex h-[calc(100vh-156px-var(--license-banner-h,0px))] min-h-0 flex-col"
      aria-label={t("detail.file_editor")}
    >
      <header className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div className="flex min-w-0 items-center gap-2">
          <Tooltip content={t("back")}>
            <Button variant="text" color="default" iconOnly aria-label={t("back")} onClick={onBack}>
              <Outlined.ArrowLeft />
            </Button>
          </Tooltip>
          <FileIcon type={file.suffix as FileType} className="size-6 shrink-0" />
          <h1 className="truncate text-heading-sm font-medium">{name}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            className="w-60"
            aria-label={t("segment.searchSegments")}
            placeholder={t("segment.searchSegments")}
            disabled={model.busy || model.failed}
            value={model.keyword}
            onChange={(event) => model.setKeyword(event.target.value)}
          />
          {model.canEdit && (
            <>
              <Button
                variant="outlined"
                color="default"
                disabled={!model.info.isSuccess || model.busy}
                onClick={() => setMetadataOpen(true)}
              >
                {t("metadialog.title")}
              </Button>
              <Button disabled={model.busy || model.failed} onClick={() => setProcessingOpen(true)}>
                {t("segment.adjustStrategy")}
              </Button>
            </>
          )}
        </div>
      </header>
      {model.failed && (
        <div role="alert" className="flex items-center gap-2">
          <p>{t("detail.save_failed")}</p>
          <Button
            variant="text"
            disabled={model.busy}
            onClick={() => {
              void model.retryWrite();
            }}
          >
            {t("retry")}
          </Button>
        </div>
      )}
      {model.preview.isError ? (
        <div role="alert">
          <p>{t("f118.load_failed")}</p>
          <Button
            onClick={() => {
              void model.preview.refetch();
            }}
          >
            {t("retry")}
          </Button>
        </div>
      ) : !model.preview.data ? (
        <p role="status">{t("loading")}</p>
      ) : (
        <>
          <div className="flex min-h-0 flex-1 gap-3 bg-background-main" aria-busy={model.busy}>
            <PreviewFile
              key={fileId}
              file={file}
              rawFiles={[file]}
              partitions={model.boxes.data ?? {}}
              chunks={chunks}
              setChunks={() => undefined}
              step={3}
              edit={model.canEdit && !model.busy && !model.failed}
              urlState={{
                load: true,
                url: model.preview.data.preview_url || model.preview.data.original_url,
              }}
              previewUrl={model.preview.data.preview_url || model.preview.data.original_url}
              previewData={model.preview.data}
            />
            <div className="flex min-h-0 min-w-0 flex-1 flex-col pr-3">
              {model.chunks.isError ? (
                <div role="alert" className="p-4">
                  <p>{t("f118.load_failed")}</p>
                  <Button
                    onClick={() => {
                      void model.chunks.refetch();
                    }}
                  >
                    {t("retry")}
                  </Button>
                </div>
              ) : (
                <PreviewParagraph
                  key={`${fileId}:${model.chunks.dataUpdatedAt}`}
                  fileId={String(fileId)}
                  previewCount={chunks.length}
                  page={model.page}
                  edit={model.canEdit && !model.busy && !model.failed}
                  canDelete={model.canEdit && !model.busy && !model.failed}
                  fileSuffix={file.suffix}
                  loading={model.chunks.isInitialLoading || model.busy}
                  chunks={chunks}
                  className="min-h-0 flex-1 pb-4"
                  onDel={handleDelete}
                  onChange={model.handleChange}
                />
              )}
            </div>
          </div>
          <div className="py-3">
            <Pagination
              current={model.page}
              pageSize={10}
              total={model.chunks.data?.total ?? 0}
              disabled={model.busy || model.failed}
              onChange={model.setPage}
              locale={locale}
              showTotal
            />
          </div>
        </>
      )}
      {metadataOpen && model.canEdit && model.info.data && (
        <SpaceFileMetadataDialog
          scope={scope}
          spaceId={spaceId}
          fileId={fileId}
          info={model.info.data}
          onClose={() => setMetadataOpen(false)}
          onSaved={() => model.info.refetch()}
        />
      )}
      <SpaceProcessingDialog
        scope={scope}
        spaceId={spaceId}
        fileId={fileId}
        mode="file"
        open={processingOpen && model.canEdit}
        onOpenChange={setProcessingOpen}
        onSaved={() => {
          void model.chunks.refetch();
        }}
      />
    </section>
  );
}
