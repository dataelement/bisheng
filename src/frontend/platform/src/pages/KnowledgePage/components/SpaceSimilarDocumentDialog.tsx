import { Button } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSearch } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { readPendingSimilarFiles, type KnowledgeVersionsApi } from "@/controllers/API/knowledgeVersions";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { SpaceSimilarDocumentPanel } from "./SpaceSimilarDocumentPanel";

interface SpaceSimilarDocumentDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  restrictToFileIds?: number[];
  api?: KnowledgeVersionsApi;
  onOpenChange: (open: boolean) => void;
}
export function SpaceSimilarDocumentDialog(props: SpaceSimilarDocumentDialogProps) {
  return <SimilarReview key={JSON.stringify([props.scope, props.spaceId, props.restrictToFileIds])} {...props} />;
}
function SimilarReview({ scope, spaceId, restrictToFileIds, api, onOpenChange }: SpaceSimilarDocumentDialogProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [processed, setProcessed] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const alive = useRef(true);
  const opening = useId();
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const enabled = Boolean(scope.identityKey) && Number.isSafeInteger(scope.tenantId) && scope.tenantId > 0 && Number.isSafeInteger(spaceId) && spaceId > 0 && (restrictToFileIds ?? []).every(id => Number.isSafeInteger(id) && id > 0);
  const pending = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "pending-similar", opening],
    queryFn: ({ signal }) => readPendingSimilarFiles(spaceId, signal),
    enabled, retry: false, cacheTime: 0,
  });
  useEffect(() => { if (pending.error) showApiError(pending.error); }, [pending.error]);
  const visible = (pending.data ?? []).filter(file => !processed.includes(file.knowledge_file_id) && (!restrictToFileIds?.length || restrictToFileIds.includes(file.knowledge_file_id)));
  const selected = visible.find(file => file.knowledge_file_id === selectedId) ?? visible[0];
  const handleChanged = async () => {
    if (!alive.current || !selected) return;
    setProcessed(previous => [...previous, selected.knowledge_file_id]);
    setSelectedId(null);
    await client.invalidateQueries({ queryKey: knowledgeQueryKeys.space(scope, spaceId) });
  };
  return <Dialog open onOpenChange={open => { if (!busy) onOpenChange(open); }}>
    <DialogContent className="flex max-h-[80vh] min-h-[560px] max-w-[960px] flex-col gap-0 overflow-hidden p-0" close={!busy} aria-describedby={undefined}
      onEscapeKeyDown={event => { if (busy) event.preventDefault(); }} onPointerDownOutside={event => { if (busy) event.preventDefault(); }}>
      <DialogHeader className="shrink-0 border-b border-border-base px-6 py-4"><DialogTitle>{t("versions.similar")}</DialogTitle></DialogHeader>
      {!enabled ? <p role="alert" className="p-6">{t("f118.scope_unavailable")}</p> : pending.isError ? <div role="alert" className="p-6"><p>{t("detail.load_failed")}</p><Button onClick={() => void pending.refetch()}>{t("retry")}</Button></div>
        : pending.isInitialLoading ? <p role="status" className="p-6">{t("loading")}</p>
        : !selected ? <p className="p-6 text-center text-text-3">{t("similarReview.empty")}</p>
        : <div className="flex min-h-0 flex-1 overflow-hidden">
          <aside className="flex w-1/3 shrink-0 flex-col border-r border-border-base bg-fill-2 sm:w-[260px]">
            <p className="border-b border-border-base px-5 py-4 text-xs text-text-3">{t("similarReview.pendingCount", { count: visible.length })}</p>
            <div className="flex-1 overflow-y-auto p-3">
              {visible.map(file => <button type="button" key={file.knowledge_file_id} disabled={busy || uncertain} aria-pressed={selected.knowledge_file_id === file.knowledge_file_id}
                className={`mb-1 flex w-full items-start gap-2 rounded-lg px-3 py-3 text-left hover:bg-fill-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${selected.knowledge_file_id === file.knowledge_file_id ? "bg-primary/10 text-primary" : "text-text-1"}`}
                onClick={() => setSelectedId(file.knowledge_file_id)}>
                <FileSearch className="mt-0.5 size-4 shrink-0" /><span className="min-w-0"><span className="block truncate text-sm font-medium" title={file.file_name}>{file.file_name}</span><span className="mt-1 block text-xs text-text-3">{t("similarReview.recommendCount", { count: file.candidate_count })}</span></span>
              </button>)}
            </div>
          </aside>
          <div className="min-w-0 flex-1 overflow-y-auto">
            <SpaceSimilarDocumentPanel scope={scope} spaceId={spaceId} fileId={selected.knowledge_file_id} file={selected} api={api} disabled={uncertain} onUncertain={() => setUncertain(true)} onChanged={handleChanged} onBusyChange={setBusy} />
          </div>
        </div>}
    </DialogContent>
  </Dialog>;
}
