/**
 * The memories one search step returned, listed where the step is (F132, AC-87).
 *
 * A step event carries item ids only. The text comes from the owner's own item
 * list, so a viewer who is not the owner — or an item deleted since — finds no
 * match, and the list says the items are gone instead of showing anyone else's
 * memory. Each item can be deleted in place.
 */
import { Button } from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { deleteMemoryItemApi, listMemoryItemsApi, memoryErrorMessage, type MemoryItem } from "~/api/memory";
import { useLocalize } from "~/hooks";

/** Same key as the settings page, so a delete in either place updates both. */
export const MEMORY_ITEMS_KEY = ["memory", "items"] as const;

export interface MemorySearchHitsProps {
  itemIds: string[];
}

export function MemorySearchHits({ itemIds }: MemorySearchHitsProps) {
  const localize = useLocalize();
  const queryClient = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { data, isError, refetch } = useQuery({
    queryKey: MEMORY_ITEMS_KEY,
    queryFn: listMemoryItemsApi,
    staleTime: 30_000,
  });
  const remove = useMutation({
    mutationFn: (itemId: string) => deleteMemoryItemApi(itemId),
    onSuccess: (_result, itemId) => {
      setErrors((prev) => ({ ...prev, [itemId]: "" }));
      queryClient.setQueryData<MemoryItem[]>(MEMORY_ITEMS_KEY, (old) => old?.filter((i) => i.id !== itemId));
      void queryClient.invalidateQueries({ queryKey: MEMORY_ITEMS_KEY });
    },
    onError: (err, itemId) =>
      setErrors((prev) => ({ ...prev, [itemId]: memoryErrorMessage(err, localize("memory.delete_failed")) })),
  });

  if (isError) {
    return (
      <div className="flex items-center gap-2 text-xs leading-5 text-text-3">
        {localize("memory.load_failed")}
        <Button size="small" variant="text" color="default" onClick={() => void refetch()}>
          {localize("memory.retry")}
        </Button>
      </div>
    );
  }
  if (!data) return <p className="text-xs leading-5 text-text-3">{localize("memory.loading")}</p>;

  const byId = new Map(data.map((item) => [item.id, item]));
  const hits = itemIds.map((id) => byId.get(id)).filter((item): item is MemoryItem => !!item);
  if (!hits.length) return <p className="text-xs leading-5 text-text-3">{localize("memory.step.hits_gone")}</p>;

  return (
    <ul className="flex flex-col gap-1.5" data-slot="memory-search-hits">
      {hits.map((item) => {
        const deleting = remove.isLoading && remove.variables === item.id;
        return (
          <li key={item.id} className="flex flex-col">
            <div className="flex items-start gap-3">
              <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-xs leading-5 text-text-2">
                {item.content}
              </p>
              <button
                type="button"
                className="shrink-0 rounded-sm text-xs leading-5 text-text-3 transition-colors hover:text-danger focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-default disabled:opacity-50"
                disabled={deleting}
                aria-busy={deleting}
                onClick={() => remove.mutate(item.id)}
              >
                {localize("memory.delete")}
              </button>
            </div>
            {errors[item.id] && (
              <p role="alert" className="text-xs leading-5 text-danger">
                {errors[item.id]}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
