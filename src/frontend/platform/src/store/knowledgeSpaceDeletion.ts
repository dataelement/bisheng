import { create } from "zustand";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";

type Deletion = { operationId: string; phase: "deleting" | "deleted" };
const key = (scope: KnowledgeQueryScope, spaceId: number) =>
  JSON.stringify([
    scope.identityKey,
    scope.tenantId,
    scope.managementTenantId,
    scope.view,
    spaceId,
  ]);

// UI lifecycle only. Authorization and completion remain server decisions.
export const useKnowledgeSpaceDeletion = create<{
  entries: Readonly<Record<string, Deletion>>;
}>(() => ({ entries: {} }));

export function setSpaceDeletion(
  scope: KnowledgeQueryScope,
  spaceId: number,
  operationId: string,
  phase: Deletion["phase"],
) {
  useKnowledgeSpaceDeletion.setState(({ entries }) => ({
    entries: { ...entries, [key(scope, spaceId)]: { operationId, phase } },
  }));
}

export function releaseSpaceDeletion(
  scope: KnowledgeQueryScope,
  spaceId: number,
  operationId: string,
) {
  useKnowledgeSpaceDeletion.setState(({ entries }) => {
    const id = key(scope, spaceId);
    if (
      entries[id]?.operationId !== operationId ||
      entries[id]?.phase !== "deleting"
    )
      return { entries };
    const next = { ...entries };
    delete next[id];
    return { entries: next };
  });
}

export function isSpaceDeletionActive(
  scope: KnowledgeQueryScope,
  spaceId: number,
) {
  return !!useKnowledgeSpaceDeletion.getState().entries[key(scope, spaceId)];
}

export function useSpaceDeletionActive(
  scope: KnowledgeQueryScope,
  spaceId: number,
) {
  return useKnowledgeSpaceDeletion(
    ({ entries }) => !!entries[key(scope, spaceId)],
  );
}
