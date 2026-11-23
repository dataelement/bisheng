import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listOwnedSpaceCopies } from "@/controllers/API/knowledgeCopy";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { isSpaceDeletionActive } from "@/store/knowledgeSpaceDeletion";
import { showApiError } from "@/controllers/request";

export function useSpaceCopyTasks(scope: KnowledgeQueryScope) {
  const client = useQueryClient();
  const scopeKey = knowledgeQueryKeys.scope(scope);
  const query = useQuery({
    queryKey: [...scopeKey, "copy-tasks"],
    queryFn: listOwnedSpaceCopies,
    enabled: Boolean(scope.identityKey) && scope.tenantId > 0,
    refetchInterval: 3000,
    cacheTime: 0,
    retry: false,
  });
  const previous = useRef<{ scope: string; states: Map<number, string> }>();
  const scopeIdentity = JSON.stringify(scopeKey);
  useEffect(() => {
    if (!query.data) return;
    const states = new Map((query.data ?? []).map(task => [task.id, `${task.job_id}:${task.state}:${task.phase}:${task.job_state}`]));
    const prior = previous.current?.scope === scopeIdentity ? previous.current.states : undefined;
    const changed = new Set([...states.keys(), ...(prior?.keys() ?? [])].filter(id => states.get(id) !== prior?.get(id)));
    if (prior && changed.size > 0) {
      void client.invalidateQueries({
        queryKey: scopeKey,
        predicate: ({ queryKey }) => {
          const [kind, spaceId] = queryKey.slice(scopeKey.length);
          if (kind === "space") {
            const id = Number(spaceId);
            return states.has(id) && changed.has(id) && !isSpaceDeletionActive(scope, id);
          }
          return ["visible-list", "admin-list", "navigation-catalog", "navigation-sections"].includes(String(kind));
        },
      });
    }
    previous.current = { scope: scopeIdentity, states };
  }, [client, scope, scopeKey, scopeIdentity, query.data]);
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  return query;
}
