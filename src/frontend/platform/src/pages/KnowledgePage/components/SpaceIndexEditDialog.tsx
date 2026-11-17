import { Button, Input, Pagination, StateView, Textarea } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { readProcessingTarget } from "@/controllers/API/knowledgeProcessing";
import {
  readVersionChunks,
  updateVersionChunk,
  deleteVersionChunk,
  readFileMetadata,
  updateFileMetadata,
} from "@/controllers/API/knowledgeIndex";
import {
  knowledgeQueryKeys,
  useKnowledgeSpaceInfo,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";

interface SpaceIndexEditDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  fileId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}
export function SpaceIndexEditDialog(props: SpaceIndexEditDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {props.open && (
        <Content
          key={JSON.stringify([props.scope, props.spaceId, props.fileId])}
          {...props}
        />
      )}
    </Dialog>
  );
}
function Content({ scope, spaceId, fileId }: SpaceIndexEditDialogProps) {
  const { t } = useTranslation("knowledge");
  const locale = usePaginationLocale();
  const metadataHeadingId = useId();
  const [page, setPage] = useState(1),
    [busy, setBusy] = useState(false),
    [text, setText] = useState<Record<number, string>>({});
  const [values, setValues] = useState<Record<string, string> | null>(null);
  const current = useRef(true);
  useEffect(() => {
    current.current = true;
    return () => {
      current.current = false;
    };
  }, []);
  const space = useKnowledgeSpaceInfo(scope, spaceId);
  const target = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "processing-target",
      fileId,
    ],
    queryFn: () => readProcessingTarget(spaceId, fileId),
    enabled: Boolean(scope.identityKey),
    cacheTime: 0,
  });
  const chunks = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "physical-chunks",
      fileId,
      page,
    ],
    queryFn: () => readVersionChunks(spaceId, fileId, page),
    enabled: target.isSuccess && Boolean(scope.identityKey),
    cacheTime: 0,
  });
  const metadata = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "physical-metadata",
      fileId,
    ],
    queryFn: () => readFileMetadata(fileId),
    enabled: target.isSuccess && Boolean(scope.identityKey),
    cacheTime: 0,
  });
  useEffect(() => {
    if (metadata.data)
      setValues(
        Object.fromEntries(
          Object.entries(metadata.data.user_metadata ?? {}).map(
            ([key, row]) => [key, String(row.field_value ?? "")],
          ),
        ),
      );
  }, [metadata.data]);
  useEffect(() => {
    const error = space.error || target.error || chunks.error || metadata.error;
    if (error) showApiError(error);
  }, [space.error, target.error, chunks.error, metadata.error]);
  const handleWrite = async (operation: () => Promise<unknown>) => {
    if (busy || !target.data) return;
    setBusy(true);
    try {
      await operation();
      if (current.current) {
        setText({});
        await chunks.refetch();
        await metadata.refetch();
      }
    } finally {
      if (current.current) setBusy(false);
    }
  };
  const entries = Object.entries(values ?? {});
  const availableFields = space.data?.metadata_fields?.filter(
    (row) => typeof row.field_name === "string" && values && !(row.field_name in values),
  ) ?? [];
  const showSave = metadata.isSuccess && values !== null && (
    entries.length > 0 || Object.keys(metadata.data.user_metadata ?? {}).length > 0
  );
  return (
    <DialogContent
      className="max-h-[85vh] max-w-3xl overflow-y-auto"
      aria-describedby={undefined}
    >
      <DialogHeader>
        <DialogTitle>{t("f118.index_edit_title")}</DialogTitle>
      </DialogHeader>
      <fieldset disabled={busy || !target.data} className="space-y-4">
        <section aria-labelledby={metadataHeadingId} className="space-y-3">
          <h3 id={metadataHeadingId} className="text-h4 text-text-1">{t("f118.index_metadata")}</h3>
          {(space.isInitialLoading || target.isInitialLoading || metadata.isInitialLoading) && (
            <p role="status" className="text-body text-text-3">{t("loading")}</p>
          )}
          {space.isSuccess && metadata.isSuccess && values !== null && !entries.length && !availableFields.length && (
            <StateView size="inline" title={t("f118.index_metadata_empty")} className="rounded-md bg-fill-1" />
          )}
          {entries.map(([key, value]) => (
            <div className="flex gap-2" key={key}>
              <label className="min-w-0 grow space-y-2 text-body">
                {key}
                <Input
                  value={value}
                  onChange={(event) =>
                    setValues({ ...values, [key]: event.target.value })
                  }
                />
              </label>
              <Button
                variant="text"
                onClick={() =>
                  setValues(
                    Object.fromEntries(
                      Object.entries(values ?? {}).filter(([name]) => name !== key),
                    ),
                  )
                }
              >
                {t("delete")}
              </Button>
            </div>
          ))}
          {availableFields.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {availableFields.map((row) => (
                <Button
                  variant="outlined"
                  key={String(row.field_name)}
                  onClick={() =>
                    setValues({ ...values, [String(row.field_name)]: "" })
                  }
                >
                  {String(row.field_name)}
                </Button>
              ))}
            </div>
          )}
          {showSave && (
            <Button
              onClick={() =>
                void handleWrite(() => updateFileMetadata(fileId, values!)).catch(
                  showApiError,
                )
              }
            >
              {t("save")}
            </Button>
          )}
        </section>
        <h3>{t("f118.index_chunks")}</h3>
        {chunks.data?.data.map((chunk) => (
          <div
            key={chunk.metadata.chunk_index}
            className="space-y-2 border-t pt-2"
          >
            <Textarea
              value={text[chunk.metadata.chunk_index] ?? chunk.text}
              onChange={(event) =>
                setText({
                  ...text,
                  [chunk.metadata.chunk_index]: event.target.value,
                })
              }
            />
            <div className="flex gap-2">
              <Button
                onClick={() =>
                  void handleWrite(() =>
                    updateVersionChunk(
                      spaceId,
                      fileId,
                      chunk,
                      text[chunk.metadata.chunk_index] ?? chunk.text,
                    ),
                  ).catch(showApiError)
                }
              >
                {t("save")}
              </Button>
              <Button
                variant="outlined"
                onClick={() =>
                  bsConfirm({
                    title: t("f118.index_delete_chunk"),
                    desc: t("f118.index_delete_chunk"),
                    onOk: () =>
                      handleWrite(() =>
                        deleteVersionChunk(spaceId, fileId, chunk),
                      ),
                  })
                }
              >
                {t("delete")}
              </Button>
            </div>
          </div>
        ))}
      </fieldset>
      {chunks.data && chunks.data.total > 10 && (
        <Pagination
          current={page}
          total={chunks.data.total}
          pageSize={10}
          onChange={setPage}
          locale={locale}
        />
      )}
    </DialogContent>
  );
}
