import type { UseVisibleKnowledgeSelectionsOptions } from "./chatSurfaceTypes";
import { useEffect, useMemo } from "react";
import { useGetOrgToolList } from "~/hooks/queries/data-provider";
import { retainVisibleOrgKnowledgeSelections } from "../filterVisibleKnowledgeSelections";

export function useVisibleKnowledgeSelections({
  user,
  selectedOrgKbs,
  setSelectedOrgKbs,
}: UseVisibleKnowledgeSelectionsOptions) {
  const selectedOrgKbIds = useMemo(
    () =>
      selectedOrgKbs
        .filter((item) => item.type === "org")
        .map((item) => String(item.id)),
    [selectedOrgKbs],
  );
  const selectedOrgKbIdsKey = selectedOrgKbIds.join(",");
  const {
    data: visibleSelectedOrgKbs = [],
    isSuccess: selectedOrgKbVisibilityReady,
  } = useGetOrgToolList(
    {
      page: 1,
      page_size: Math.max(1, selectedOrgKbIds.length),
      sort_by: "name",
      preferred_ids: selectedOrgKbIdsKey,
      action: "visible",
    },
    { enabled: !!user?.id && selectedOrgKbIds.length > 0 },
  );

  // Revalidate persisted selections as well as new defaults. Without this,
  // an org KB cached before its visibility was revoked remains exposed as a
  // chip even after the user-facing workstation config starts filtering it.
  useEffect(() => {
    if (!selectedOrgKbVisibilityReady || !selectedOrgKbIds.length) return;
    const visibleIds = visibleSelectedOrgKbs.map(
      (item: { id: string | number }) => item.id,
    );
    setSelectedOrgKbs((current) =>
      retainVisibleOrgKnowledgeSelections(current, visibleIds),
    );
  }, [
    selectedOrgKbIdsKey,
    selectedOrgKbIds.length,
    selectedOrgKbVisibilityReady,
    visibleSelectedOrgKbs,
    setSelectedOrgKbs,
  ]);
}
