import { useCallback, useState } from "react";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import type { DirectoryViewMode } from "./SpaceDirectoryView";

/** Directory's identity/tenant key remounts this preference with each scope. */
export function useWorkspaceViewMode(
  scope: KnowledgeQueryScope,
  enabled: boolean,
) {
  const storageKey = `knowledge-view-mode:${JSON.stringify([
    scope.identityKey,
    scope.tenantId,
    scope.managementTenantId,
    scope.view,
  ])}`;
  const [viewMode, setViewMode] = useState<DirectoryViewMode>(() => {
    if (!enabled) return "list";
    try {
      const stored = window.localStorage.getItem(storageKey);
      return stored === "card" || stored === "list" ? stored : "list";
    } catch {
      return "list";
    }
  });
  const handleViewModeChange = useCallback(
    (mode: DirectoryViewMode) => {
      setViewMode(mode);
      if (!enabled) return;
      try {
        window.localStorage.setItem(storageKey, mode);
      } catch {
        // Storage restrictions must not block an in-memory display preference.
      }
    },
    [enabled, storageKey],
  );
  return [viewMode, handleViewModeChange] as const;
}
