/**
 * One memory, opened from the memory list (F132, AC-88 / AC-107).
 *
 * Laid out like Claude's memory page: last updated, summary, details (markdown). It
 * is changed only by telling the AI how (the box pinned at the bottom), or deleted. An AI change applies at once and can be undone, which edits the item back
 * to the version before.
 */
import { Button, Tag } from "@bisheng/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { lazy, Suspense, useState, type KeyboardEvent } from "react";
import {
  editMemoryItemApi,
  getMemoryItemDetailApi,
  memoryErrorMessage,
  reviseMemoryItemApi,
  type MemoryItem,
  type MemoryItemVersion,
} from "~/api/memory";
import { memorySourceLabel, memoryTypeLabel } from "~/components/Memory/memoryLabels";
import { useLocalize } from "~/hooks";

// Loaded on demand: the markdown stack is heavy and only an opened memory needs it.
const MarkdownLite = lazy(() => import("~/components/Chat/Messages/Content/MarkdownLite"));

export interface MemoryDetailViewProps {
  item: MemoryItem;
  onBack: () => void;
  onDelete: (item: MemoryItem) => void;
  /** The item was replaced by a new version (AI change or its undo): follow the new id. */
  onReplaced: (newItemId: string) => Promise<void>;
}

type Notice = { kind: "revised"; previous: MemoryItemVersion } | { kind: "unchanged" } | null;

export function MemoryDetailView({ item, onBack, onDelete, onReplaced }: MemoryDetailViewProps) {
  const localize = useLocalize();
  const [instruction, setInstruction] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [error, setError] = useState("");

  const detailQuery = useQuery({
    queryKey: ["memory", "detail", item.id],
    queryFn: () => getMemoryItemDetailApi(item.id),
    enabled: item.has_detail,
  });

  const revise = useMutation({
    mutationFn: (text: string) => reviseMemoryItemApi(item.id, text),
    onSuccess: async (result) => {
      setError("");
      if (!result.changed) {
        setNotice({ kind: "unchanged" });
        return;
      }
      setInstruction("");
      await onReplaced(result.item_id);
      setNotice({ kind: "revised", previous: result.previous });
    },
    onError: (err) => setError(memoryErrorMessage(err, localize("memory.revise_failed"))),
  });

  const undo = useMutation({
    mutationFn: (previous: MemoryItemVersion) =>
      editMemoryItemApi(item.id, {
        content: previous.summary,
        type: previous.type,
        event_time: previous.event_time,
        detail: previous.detail,
      }),
    onSuccess: async (result) => {
      setError("");
      setNotice(null);
      await onReplaced(result.item_id);
    },
    onError: (err) => setError(memoryErrorMessage(err, localize("memory.save_failed"))),
  });

  const submit = () => {
    const text = instruction.trim();
    if (!text || revise.isLoading) return;
    setNotice(null);
    revise.mutate(text);
  };
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter breaks the line; never while an IME is composing.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const section = (label: string, body: React.ReactNode) => (
    <section className="flex flex-col gap-2">
      <h4 className="text-body-sm text-text-3">{label}</h4>
      {body}
    </section>
  );

  const detailBody = () => {
    if (!item.has_detail) return <p className="text-body text-text-3">{localize("memory.no_detail")}</p>;
    if (detailQuery.isError) {
      return (
        <div className="flex items-center gap-2 text-body-sm text-text-3">
          {memoryErrorMessage(detailQuery.error, localize("memory.detail_load_failed"))}
          <Button size="small" variant="text" color="default" onClick={() => void detailQuery.refetch()}>
            {localize("memory.retry")}
          </Button>
        </div>
      );
    }
    if (detailQuery.isLoading) return <p className="text-body-sm text-text-3">{localize("memory.loading")}</p>;
    return (
      // Body text under the heading; markdown lists and paragraphs keep their structure.
      <div className="break-words text-body leading-7 text-text-1 [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-5">
        <Suspense fallback={<p className="whitespace-pre-wrap">{detailQuery.data ?? ""}</p>}>
          <MarkdownLite content={detailQuery.data ?? ""} codeExecution={false} />
        </Suspense>
      </div>
    );
  };

  return (
    // Tall enough that the AI box sits at the bottom of the window, like a chat composer.
    <div className="flex min-h-[calc(100dvh-148px)] flex-col" data-memory-detail={item.id}>
      <div className="flex items-center justify-between gap-2">
        <Button size="small" variant="text" color="default" onClick={onBack}>
          <Outlined.ArrowLeft />
          {localize("memory.back")}
        </Button>
        <Button size="small" variant="outlined" color="danger" onClick={() => onDelete(item)}>
          {localize("memory.delete")}
        </Button>
      </div>

      {/* Same order as Claude's memory page: when it changed, the one-line summary, then the
          details. Type, source and event date ride in one quiet row above. */}
      <article className="mt-4 flex flex-col gap-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-text-3">
          <Tag size="small">{memoryTypeLabel(item.type, localize)}</Tag>
          <span>{memorySourceLabel(item.source, localize)}</span>
          {item.event_time && <span>{localize("memory.event_time_value", { time: item.event_time })}</span>}
        </div>
        {section(localize("memory.updated_at"), <p className="text-body text-text-1">{item.recorded_at ?? ""}</p>)}
        {section(
          localize("memory.summary_label"),
          <p className="whitespace-pre-wrap break-words text-body text-text-1">{item.content}</p>,
        )}
        {section(localize("memory.detail_label"), detailBody())}
      </article>

      {/* Tell the AI how to change this memory: pinned to the bottom of the pane. */}
      <div className="sticky bottom-0 mt-auto bg-white pb-2 pt-6">
        {notice && (
          <div className="mb-2 flex items-center gap-2 text-body-sm text-text-2" role="status">
            {notice.kind === "revised" ? (
              <>
                <span>{localize("memory.revised")}</span>
                <Button
                  size="small"
                  variant="text"
                  color="default"
                  loading={undo.isLoading}
                  onClick={() => undo.mutate(notice.previous)}
                >
                  {localize("memory.undo")}
                </Button>
              </>
            ) : (
              <span>{localize("memory.revise_unchanged")}</span>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="mb-2 text-body-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex items-end gap-2 rounded-2xl border border-border-base bg-white px-4 py-3 shadow-sm focus-within:border-border-deep">
          <textarea
            aria-label={localize("memory.revise_label")}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={revise.isLoading}
            rows={2}
            maxLength={2000}
            placeholder={localize("memory.revise_placeholder")}
            className="max-h-40 min-h-[48px] flex-1 resize-none bg-transparent text-body text-text-1 outline-none placeholder:text-text-3"
          />
          <Button
            size="small"
            iconOnly
            aria-label={localize("memory.revise_send")}
            title={localize("memory.revise_send")}
            loading={revise.isLoading}
            disabled={!instruction.trim()}
            onClick={submit}
          >
            <Outlined.ArrowUp />
          </Button>
        </div>
      </div>
    </div>
  );
}
