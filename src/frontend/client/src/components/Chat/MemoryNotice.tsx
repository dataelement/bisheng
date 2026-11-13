/**
 * Memory notice and attribution beside one answer (F132, AC-21 / AC-22 / AC-87).
 *
 * - Operation notice: what this turn remembered, corrected or forgot, with the
 *   item text on expand and an undo per write.
 * - Attribution: one plain list of the memory this turn drew on — the
 *   retrieved items first, then the pinned (resident) items not already
 *   listed. Every item can be deleted in place.
 *
 * Everything comes from GET /api/v1/memory/turn, which answers the owner only.
 * The component renders nothing unless the answer's flags (or, in `probe`
 * mode, the turn record itself) say there is something to show.
 */
import { Button } from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useState, type ReactNode } from "react";
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
  // One list for the user: retrieved first, then pinned items not already listed.
  const retrievedIds = new Set(retrieved.map((i) => i.id));
  const referenced = [...retrieved, ...resident.filter((i) => !retrievedIds.has(i.id))];
  const showWrites = probe ? writes.length > 0 : flagged && flags.has_write;
  const showAttribution = probe ? referenced.length > 0 : flagged && flags.has_attribution;
  if (!hasKey || (!probe && !flagged) || (!showWrites && !showAttribution)) return null;

  const toggle = (next: Exclude<Panel, null>) => setPanel((cur) => (cur === next ? null : next));

  const noticeLabel = () => {
    if (!data) return localize("memory.notice.pending");
    const ops = new Set(writes.map((w) => w.op));
    const [only] = [...ops];
    if (ops.size === 1 && KNOWN_OPS.has(only)) return localize(`memory.notice.${only}`, { count: writes.length });
    return localize("memory.notice.updated", { count: writes.length });
  };

  const errorLine = (key: string) =>
    errors[key] ? (
      <p role="alert" className="text-caption text-danger">
        {errors[key]}
      </p>
    ) : null;

  // Light row actions are text buttons (Button spec §2).
  const textAction = (label: string, onClick: () => void, loading: boolean) => (
    <Button size="small" variant="text" color="default" className="shrink-0" loading={loading} onClick={onClick}>
      {label}
    </Button>
  );

  // One memory per row: [operation] content [action]. Nothing else gets its own line.
  const row = (key: string | number, body: ReactNode, action: ReactNode, errorKey: string, op?: string) => (
    <li key={key} className="flex flex-col" data-op={op}>
      <div className="flex items-center gap-2">
        {op && mixedOps && <span className="shrink-0 text-caption text-text-3">{localize(`memory.notice.op_${op}`)}</span>}
        <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-body-sm text-text-1">{body}</p>
        {action}
      </div>
      {errorLine(errorKey)}
    </li>
  );

  const itemRow = (memory: MemoryItem) =>
    row(
      memory.id,
      memory.content,
      textAction(
        localize("memory.delete"),
        () => deleteMutation.mutate(memory.id),
        deleteMutation.isLoading && deleteMutation.variables === memory.id,
      ),
      `i${memory.id}`,
    );

  // Show the operation word per row only when one answer did different things.
  const mixedOps = new Set(writes.map((w) => w.op)).size > 1;

  const writeRow = (w: MemoryTurnWrite) => {
    const op = KNOWN_OPS.has(w.op) ? w.op : "remember";
    const gone = localize("memory.notice.item_gone");
    const body =
      op === "forget" ? (
        <s className="text-text-3">{w.related_item?.content ?? gone}</s>
      ) : op === "correct" && w.related_item ? (
        <>
          <s className="text-text-3">{w.related_item.content}</s> {w.item?.content ?? gone}
        </>
      ) : (
        (w.item?.content ?? gone)
      );
    // The item was cleared since: there is nothing left to undo.
    const missing = op === "forget" ? !w.related_item : !w.item;
    const action = missing ? null : w.undone ? (
      <span className="shrink-0 text-caption text-text-3">{localize("memory.notice.undone")}</span>
    ) : (
      textAction(
        localize("memory.notice.undo"),
        () => undoMutation.mutate(w.record_id),
        undoMutation.isLoading && undoMutation.variables === w.record_id,
      )
    );
    const shown = w.undone ? <s className="text-text-3">{body}</s> : missing ? <span className="text-text-3">{body}</span> : body;
    return row(w.record_id, shown, action, `w${w.record_id}`, op);
  };

  const entryClass =
    "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-caption text-text-3 transition-colors hover:bg-fill-2 hover:text-text-1";
  const chevron = (open: boolean) => (
    <Outlined.Down size={14} className={cn("shrink-0 transition-transform", !open && "-rotate-90")} />
  );

  const panelBody = () => {
    if (isError) {
      return (
        <div className="flex items-center gap-2 text-caption text-text-3">
          {localize("memory.load_failed")}
          {textAction(localize("memory.retry"), () => void refetch(), false)}
        </div>
      );
    }
    if (!data) return <p className="text-caption text-text-3">{localize("memory.loading")}</p>;
    if (panel === "writes") return <ul className="flex flex-col gap-1">{writes.map(writeRow)}</ul>;
    if (referenced.length === 0) {
      return <p className="text-caption text-text-3">{localize("memory.attribution.empty")}</p>;
    }
    return <ul className="flex flex-col gap-1">{referenced.map(itemRow)}</ul>;
  };

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
        // Hangs under the entry like a quote: a rule on the left, no card, no fill. The list is as
        // wide as its content (up to 560px), so each row's action stays next to its text.
        <div className="ml-2.5 w-fit max-w-[560px] border-l-2 border-border-base py-0.5 pl-3">{panelBody()}</div>
      )}
    </div>
  );
}

