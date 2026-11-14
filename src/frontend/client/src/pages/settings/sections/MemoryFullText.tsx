/**
 * The full text of a memory that has one, folded under its one-line content (F132, AC-88).
 *
 * The user is never told about "details": a long memory simply has more to show.
 * The text is read only when the user opens it, and only the owner can read it.
 */
import { Button } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { getMemoryItemDetailApi, memoryErrorMessage } from "~/api/memory";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

export interface MemoryFullTextProps {
  itemId: string;
}

export function MemoryFullText({ itemId }: MemoryFullTextProps) {
  const localize = useLocalize();
  const [open, setOpen] = useState(false);
  const { data, error, isError, isLoading, refetch } = useQuery({
    queryKey: ["memory", "detail", itemId],
    queryFn: () => getMemoryItemDetailApi(itemId),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  const body = () => {
    if (isError) {
      return (
        <div className="flex items-center gap-2 text-caption text-text-3">
          {memoryErrorMessage(error, localize("memory.full_text_failed"))}
          <Button size="small" variant="text" color="default" onClick={() => void refetch()}>
            {localize("memory.retry")}
          </Button>
        </div>
      );
    }
    if (isLoading) return <p className="text-caption text-text-3">{localize("memory.loading")}</p>;
    return <p className="whitespace-pre-wrap break-words text-body-sm text-text-2">{data ?? ""}</p>;
  };

  return (
    <>
      {/* Same size and grey as the meta line it sits in (like the memory receipt entry),
          so it reads as part of the line rather than a separate button. */}
      <button
        type="button"
        className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded text-caption text-text-3 transition-colors hover:text-text-1"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {localize(open ? "memory.full_text_hide" : "memory.full_text_show")}
        <Outlined.Down size={12} className={cn("shrink-0 transition-transform", !open && "-rotate-90")} />
      </button>
      {open && <div className="order-last mt-1 basis-full border-l-2 border-border-base pl-3">{body()}</div>}
    </>
  );
}
