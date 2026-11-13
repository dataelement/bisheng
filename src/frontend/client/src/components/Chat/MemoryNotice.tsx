/**
 * Memory notice and attribution beside one answer (F132, AC-21 / AC-22 / AC-87).
 *
 * - Operation notice: what this turn remembered, corrected or forgot, with the
 *   item text on expand and an undo per write.
 * - Attribution: the items this turn retrieved, listed one by one, and the
 *   resident memory carried into the turn, viewable as a whole. Every item can
 *   be deleted in place.
 *
 * Everything comes from GET /api/v1/memory/turn, which answers the owner only.
 * The component renders nothing unless the answer's flags (or, in `probe`
 * mode, the turn record itself) say there is something to show.
 */
import { Button, Tag } from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useState } from "react";
import {
  deleteMemoryItemApi,
  getMemoryTurnApi,
  hasMemoryFlags,
  memoryErrorMessage,
  undoMemoryWriteApi,
  type MemoryFlags,
  type MemoryItem,
  type MemoryTurn,
  type MemoryTurnWrite,
} from "~/api/memory";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

export interface MemoryNoticeProps {
  /** Flags from the stream signal or from the chat's history flags. */
  flags?: MemoryFlags | null;
  /** Explicit turn id; falls back to `flags.turn_id`. */
  turnId?: string | null;
  /** Stored answer id — used when no turn id is known (after a reload). */
  messageId?: string | null;
  /** No flags exist for this surface (deep research rounds): read the turn by
   *  message id and show whatever it holds. */
  probe?: boolean;
  className?: string;
}

const KNOWN_OPS = new Set(["remember", "correct", "forget"]);
const MEMORY_ITEMS_KEY = ["memory", "items"];

type Panel = "writes" | "attribution" | null;

export function MemoryNotice({ flags, turnId, messageId, probe = false, className }: MemoryNoticeProps) {
  const localize = useLocalize();
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<Panel>(null);
  const [residentOpen, setResidentOpen] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const key = { turnId: turnId || flags?.turn_id || undefined, messageId: messageId || undefined };
  const hasKey = !!(key.turnId || key.messageId);
  const flagged = hasMemoryFlags(flags);
  const queryKey = ["memory", "turn", key.turnId ?? "", key.messageId ?? ""];
  // A write notice needs its op names up front; attribution loads on demand.
  const enabled = hasKey && (probe || (flagged && (flags.has_write || panel === "attribution")));
  const { data, isError, refetch } = useQuery({
    queryKey,
    queryFn: () => getMemoryTurnApi(key),
    enabled,
    staleTime: 30_000,
  });

  const updateTurn = (updater: (turn: MemoryTurn) => MemoryTurn) =>
    queryClient.setQueryData<MemoryTurn>(queryKey, (old) => (old ? updater(old) : old));
  const setError = (id: string, message: string) => setErrors((prev) => ({ ...prev, [id]: message }));

  const undoMutation = useMutation({
    mutationFn: (recordId: number) => undoMemoryWriteApi(recordId),
    onSuccess: (_result, recordId) => {
      setError(`w${recordId}`, "");
      updateTurn((turn) => ({
        ...turn,
        writes: turn.writes.map((w) => (w.record_id === recordId ? { ...w, undone: true } : w)),
      }));
      void queryClient.invalidateQueries({ queryKey: MEMORY_ITEMS_KEY });
    },
    onError: (err, recordId) => setError(`w${recordId}`, memoryErrorMessage(err, localize("memory.notice.undo_failed"))),
  });

  const deleteMutation = useMutation({
    mutationFn: (itemId: string) => deleteMemoryItemApi(itemId),
    onSuccess: (_result, itemId) => {
      setError(`i${itemId}`, "");
      updateTurn((turn) => ({
        ...turn,
        retrieved: turn.retrieved.filter((i) => i.id !== itemId),
        resident: turn.resident.filter((i) => i.id !== itemId),
      }));
      void queryClient.invalidateQueries({ queryKey: MEMORY_ITEMS_KEY });
    },
    onError: (err, itemId) => setError(`i${itemId}`, memoryErrorMessage(err, localize("memory.delete_failed"))),
  });

  const writes = data?.writes ?? [];
  const retrieved = data?.retrieved ?? [];
  const resident = data?.resident ?? [];
  const showWrites = probe ? writes.length > 0 : flagged && flags.has_write;
  const showAttribution = probe ? retrieved.length + resident.length > 0 : flagged && flags.has_attribution;
  if (!hasKey || (!probe && !flagged) || (!showWrites && !showAttribution)) return null;

  const toggle = (next: Exclude<Panel, null>) => setPanel((cur) => (cur === next ? null : next));

  const noticeLabel = () => {
    if (!data) return localize("memory.notice.pending");
    const ops = new Set(writes.map((w) => w.op));
    const [only] = [...ops];
    if (ops.size === 1 && KNOWN_OPS.has(only)) return localize(`memory.notice.${only}`, { count: writes.length });
    return localize("memory.notice.updated", { count: writes.length });
  };

  const deleteButton = (memory: MemoryItem) => (
    <Button
      size="small"
      variant="text"
      color="default"
      iconOnly
      aria-label={localize("memory.delete")}
      title={localize("memory.delete")}
      loading={deleteMutation.isLoading && deleteMutation.variables === memory.id}
      onClick={() => deleteMutation.mutate(memory.id)}
    >
      <Outlined.Delete />
    </Button>
  );

  const itemRow = (memory: MemoryItem) => (
    <li key={memory.id} className="flex items-start gap-2 py-1">
      <div className="min-w-0 flex-1">
        <p className="whitespace-pre-wrap break-words text-body-sm text-text-1">{memory.content}</p>
        {errors[`i${memory.id}`] && (
          <p role="alert" className="text-caption text-danger">
            {errors[`i${memory.id}`]}
          </p>
        )}
      </div>
      {deleteButton(memory)}
    </li>
  );

  const writeRow = (w: MemoryTurnWrite) => {
    const op = KNOWN_OPS.has(w.op) ? w.op : "remember";
    const shown = op === "forget" ? w.related_item : w.item;
    const error = errors[`w${w.record_id}`];
    return (
      <li key={w.record_id} className="flex flex-col gap-0.5 py-1">
        <div className="flex items-start gap-2">
          <Tag size="small" className="shrink-0">
            {localize(`memory.notice.op_${op}`)}
          </Tag>
          <div className="min-w-0 flex-1">
            <p
              className={cn(
                "whitespace-pre-wrap break-words text-body-sm text-text-1",
                (w.undone || op === "forget") && "text-text-3",
                w.undone && "line-through",
              )}
            >
              {shown?.content ?? localize("memory.notice.item_gone")}
            </p>
            {op === "correct" && w.related_item && (
              <p className="break-words text-caption text-text-3">
                {localize("memory.notice.was", { content: w.related_item.content })}
              </p>
            )}
          </div>
          {w.undone ? (
            <span className="shrink-0 text-caption text-text-3">{localize("memory.notice.undone")}</span>
          ) : (
            <Button
              size="small"
              variant="text"
              color="default"
              className="shrink-0"
              loading={undoMutation.isLoading && undoMutation.variables === w.record_id}
              onClick={() => undoMutation.mutate(w.record_id)}
            >
              {localize("memory.notice.undo")}
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="text-caption text-danger">
            {error}
          </p>
        )}
      </li>
    );
  };

  const entryClass =
    "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption text-text-3 transition-colors hover:bg-fill-2 hover:text-text-1";
  const chevron = (open: boolean) => (
    <Outlined.Down size={14} className={cn("shrink-0 transition-transform", !open && "-rotate-90")} />
  );

  return (
    <div data-slot="memory-notice" className={cn("mt-1 flex flex-col gap-1", className)}>
      <div className="flex flex-wrap items-center gap-1">
        {showWrites && (
          <button type="button" className={entryClass} aria-expanded={panel === "writes"} onClick={() => toggle("writes")}>
            <Outlined.Bulb size={14} className="shrink-0" />
            <span>{noticeLabel()}</span>
            {chevron(panel === "writes")}
          </button>
        )}
        {showAttribution && (
          <button
            type="button"
            className={entryClass}
            aria-expanded={panel === "attribution"}
            onClick={() => toggle("attribution")}
          >
            <Outlined.History size={14} className="shrink-0" />
            <span>{localize("memory.attribution.entry")}</span>
            {chevron(panel === "attribution")}
          </button>
        )}
      </div>

      {panel && (
        <div className="rounded-lg border border-border-base bg-fill-1 px-3 py-2">
          {isError ? (
            <div className="flex items-center gap-2 text-caption text-text-3">
              {localize("memory.load_failed")}
              <Button size="small" variant="link" onClick={() => refetch()}>
                {localize("memory.retry")}
              </Button>
            </div>
          ) : !data ? (
            <p className="text-caption text-text-3">{localize("memory.loading")}</p>
          ) : panel === "writes" ? (
            <ul className="flex flex-col">{writes.map(writeRow)}</ul>
          ) : retrieved.length + resident.length === 0 ? (
            <p className="text-caption text-text-3">{localize("memory.attribution.empty")}</p>
          ) : (
            <div className="flex flex-col gap-2">
              {retrieved.length > 0 && (
                <section role="region" aria-label={localize("memory.attribution.retrieved")}>
                  <h4 className="text-caption font-medium text-text-2">{localize("memory.attribution.retrieved")}</h4>
                  <ul className="flex flex-col">{retrieved.map(itemRow)}</ul>
                </section>
              )}
              {resident.length > 0 && (
                <section role="region" aria-label={localize("memory.attribution.resident")}>
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="text-caption font-medium text-text-2">{localize("memory.attribution.resident")}</h4>
                    <Button size="small" variant="link" onClick={() => setResidentOpen((open) => !open)}>
                      {residentOpen
                        ? localize("memory.attribution.resident_hide")
                        : localize("memory.attribution.resident_view", { count: resident.length })}
                    </Button>
                  </div>
                  <p className="text-caption text-text-3">{localize("memory.attribution.resident_hint")}</p>
                  {residentOpen && <ul className="flex flex-col">{resident.map(itemRow)}</ul>}
                </section>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
