/**
 * Memory notice beside one answer: what the turn remembered, corrected or forgot (F132, AC-21 / AC-22).
 *
 * - Operation notice: what this turn remembered, corrected or forgot, with the
 *   item text on expand and an undo per write.
 * - The items a turn's memory search returned are not listed here: they belong
 *   to the search step in the thinking process (MemorySearchHits), next to the
 *   reasoning that used them (2026-11-14 ruling).
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
  getMemoryTurnApi,
  hasMemoryFlags,
  memoryErrorMessage,
  undoMemoryWriteApi,
  type MemoryFlags,
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
  /** Sit inside the answer's action row (a wrapping flex row): the entry joins
   *  the row after a divider, and the opened list takes a line of its own. */
  inline?: boolean;
  /** Inline only: draw the divider before the entry (off when the entry leads the row). */
  divider?: boolean;
  className?: string;
}

const KNOWN_OPS = new Set(["remember", "correct", "forget"]);
const MEMORY_ITEMS_KEY = ["memory", "items"];

export function MemoryNotice({
  flags,
  turnId,
  messageId,
  probe = false,
  inline = false,
  divider = true,
  className,
}: MemoryNoticeProps) {
  const localize = useLocalize();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const key = { turnId: turnId || flags?.turn_id || undefined, messageId: messageId || undefined };
  const hasKey = !!(key.turnId || key.messageId);
  const flagged = hasMemoryFlags(flags);
  const queryKey = ["memory", "turn", key.turnId ?? "", key.messageId ?? ""];
  // The entry names the operation, so the turn is read up front.
  const enabled = hasKey && (probe || (flagged && flags.has_write));
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

  const writes = data?.writes ?? [];
  const showWrites = probe ? writes.length > 0 : flagged && flags.has_write;
  if (!hasKey || (!probe && !flagged) || !showWrites) return null;

  const noticeLabel = () => {
    if (!data) return localize("memory.notice.pending");
    const ops = new Set(writes.map((w) => w.op));
    const [only] = [...ops];
    if (ops.size === 1 && KNOWN_OPS.has(only)) return localize(`memory.notice.${only}`, { count: writes.length });
    return localize("memory.notice.updated", { count: writes.length });
  };

  // Light row actions are text buttons (Button spec §2).
  const textAction = (label: string, onClick: () => void, loading: boolean) => (
    <Button size="small" variant="text" color="default" className="shrink-0" loading={loading} onClick={onClick}>
      {label}
    </Button>
  );

  // Show the operation word per row only when one answer did different things.
  const mixedOps = new Set(writes.map((w) => w.op)).size > 1;

  // One memory per row: [operation] content [action]. Nothing else gets its own line.
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
    const shown: ReactNode = w.undone ? (
      <s className="text-text-3">{body}</s>
    ) : missing ? (
      <span className="text-text-3">{body}</span>
    ) : (
      body
    );
    const errorKey = `w${w.record_id}`;
    return (
      <li key={w.record_id} className="flex flex-col" data-op={op}>
        <div className="flex items-center gap-2">
          {mixedOps && <span className="shrink-0 text-caption text-text-3">{localize(`memory.notice.op_${op}`)}</span>}
          <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-body-sm text-text-1">{shown}</p>
          {action}
        </div>
        {errors[errorKey] && (
          <p role="alert" className="text-caption text-danger">
            {errors[errorKey]}
          </p>
        )}
      </li>
    );
  };

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
    return <ul className="flex flex-col gap-1">{writes.map(writeRow)}</ul>;
  };

  const entry = (
    <button
      type="button"
      // Never shrinks: in a flex row, Chinese text could otherwise squeeze to one character per line.
      className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-caption text-text-3 transition-colors hover:bg-fill-2 hover:text-text-1"
      aria-expanded={open}
      onClick={() => setOpen((v) => !v)}
    >
      <Outlined.Bulb size={14} className="shrink-0" />
      <span>{noticeLabel()}</span>
      <Outlined.Down size={14} className={cn("shrink-0 transition-transform", !open && "-rotate-90")} />
    </button>
  );
  // Hangs under the entry like a quote: a rule on the left, no card, no fill. The list is as
  // wide as its content (up to 560px), so each row's action stays next to its text.
  const panel = open && (
    <div className={cn("ml-2.5 w-fit max-w-[560px] border-l-2 border-border-base py-0.5 pl-3", inline && "mt-1")}>
      {panelBody()}
    </div>
  );

  if (inline) {
    return (
      <div data-slot="memory-notice" className={cn("contents", className)}>
        {divider && <span className="mx-1 h-3 w-px shrink-0 bg-border-base" aria-hidden="true" />}
        {entry}
        {/* Last in the wrapping row and full width: the list opens on a line of its own. */}
        {panel && <div className="order-last basis-full">{panel}</div>}
      </div>
    );
  }
  return (
    <div data-slot="memory-notice" className={cn("mt-1 flex flex-col gap-1", className)}>
      <div className="flex flex-wrap items-center gap-1">{entry}</div>
      {panel}
    </div>
  );
}
