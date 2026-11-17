import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listOwnedSpaceCopies } from "@/controllers/API/knowledgeCopy";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
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
  const previous = useRef<string>();
  const signature = query.data?.map((task) => `${task.id}:${task.phase}:${task.job_state}`).join("|");
  useEffect(() => {
    if (signature === undefined) return;
    if (previous.current !== undefined && previous.current !== signature) {
      void client.invalidateQueries({
        queryKey: scopeKey,
        predicate: (cached) => !cached.queryKey.includes("copy-tasks"),
      });
    }
    previous.current = signature;
  }, [signature, client, scopeKey]);
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  return query;
}
