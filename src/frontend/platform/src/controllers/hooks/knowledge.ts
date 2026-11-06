import { useState, useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceApi,
  type KnowledgeSpaceInfo,
  type KnowledgeChildrenQuery,
  type KnowledgeAdminQuery,
  type ProcessingJobsQuery,
  type ProcessingItemsQuery,
  type ProcessingPrecheckRequest,
  type ProcessingSettingsWrite,
  type ProcessingCreateRequest,
  type ProcessingRetryRequest,
} from "../API/knowledgeSpace";
import { getKnowledgeDetailApi } from "../API";

// Keep failed detail requests rejected so dependent mutations cannot use empty data.
export const useKnowledgeDetails = (
  knowledgeIds: readonly (number | string)[] | null | undefined,
) => {
  const [details, setDetails] = useState<KnowledgeSpaceInfo[]>([]);
  const [error, setError] = useState<unknown>(null);

  const fetchDetails = async (
    ids: readonly (number | string)[] | null | undefined,
  ) => {
    if (!ids?.length) return [];
    const res = (await getKnowledgeDetailApi(
      ids,
    )) as unknown as KnowledgeSpaceInfo[];
    setDetails(res);
    setError(null);
    return res;
  };

  // Preserve the original initial failure as state; the creation action can retry.
  useEffect(() => {
    void fetchDetails(knowledgeIds).catch(setError);
  }, []);

  return [details, fetchDetails, error] as const;
};

export interface KnowledgeQueryScope {
  readonly identityKey: string;
  readonly tenantId: number;
  readonly managementTenantId: number | null;
  readonly view: "ordinary" | "admin";
}

const scopeKey = (scope: KnowledgeQueryScope) =>
  [
    "f118-knowledge",
    scope.identityKey,
    scope.tenantId,
    scope.managementTenantId,
    scope.view,
  ] as const;
const spaceKey = (scope: KnowledgeQueryScope, spaceId: number) =>
  [...scopeKey(scope), "space", spaceId] as const;

export const knowledgeQueryKeys = {
  scope: scopeKey,
  space: spaceKey,
  info: (scope: KnowledgeQueryScope, spaceId: number) =>
    [...spaceKey(scope, spaceId), "info"] as const,
  children: (
    scope: KnowledgeQueryScope,
    spaceId: number,
    query: KnowledgeChildrenQuery = {},
  ) =>
    [
      ...spaceKey(scope, spaceId),
      "children",
      {
        ...query,
        file_ids: query.file_ids?.slice(),
        file_status: query.file_status?.slice(),
      },
    ] as const,
  admin: (scope: KnowledgeQueryScope, query: KnowledgeAdminQuery) =>
    [...scopeKey(scope), "admin-list", { ...query }] as const,
  settings: (scope: KnowledgeQueryScope, spaceId: number) =>
    [...spaceKey(scope, spaceId), "settings"] as const,
  jobs: (
    scope: KnowledgeQueryScope,
    spaceId: number,
    query: ProcessingJobsQuery,
  ) => [...spaceKey(scope, spaceId), "jobs", { ...query }] as const,
  job: (scope: KnowledgeQueryScope, spaceId: number, jobId: string) =>
    [...spaceKey(scope, spaceId), "job", jobId] as const,
  items: (
    scope: KnowledgeQueryScope,
    spaceId: number,
    jobId: string,
    query: ProcessingItemsQuery,
  ) =>
    [...spaceKey(scope, spaceId), "job", jobId, "items", { ...query }] as const,
};

function useKnowledgeScope(scope: KnowledgeQueryScope) {
  const client = useQueryClient();
  const { identityKey, tenantId, managementTenantId, view } = scope;
  const stableScope = useMemo(
    () => ({ identityKey, tenantId, managementTenantId, view }),
    [identityKey, tenantId, managementTenantId, view],
  );
  const current = useMemo(() => scopeKey(stableScope), [stableScope]);
  const previous = useRef(current);
  useEffect(() => {
    if (previous.current !== current) {
      const retired = previous.current;
      void client.cancelQueries({ queryKey: retired });
      client.removeQueries({ queryKey: retired });
      previous.current = current;
    }
  }, [client, current]);
  return { client, current, stableScope };
}

function canQuery(scope: KnowledgeQueryScope, spaceId?: number) {
  return (
    Boolean(scope.identityKey) &&
    Number.isSafeInteger(scope.tenantId) &&
    scope.tenantId > 0 &&
    (spaceId === undefined || (Number.isSafeInteger(spaceId) && spaceId > 0))
  );
}

export function useKnowledgeSpaceInfo(
  scope: KnowledgeQueryScope,
  spaceId: number,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.info(scope, spaceId),
    queryFn: () => api.getSpaceInfo(spaceId),
    enabled: canQuery(scope, spaceId),
    keepPreviousData: false,
  });
}
export function useKnowledgeSpaceChildren(
  scope: KnowledgeQueryScope,
  spaceId: number,
  query: KnowledgeChildrenQuery = {},
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.children(scope, spaceId, query),
    queryFn: () => api.listChildren(spaceId, query),
    enabled: canQuery(scope, spaceId),
    keepPreviousData: false,
  });
}
export function useKnowledgeAdminSpaces(
  scope: KnowledgeQueryScope,
  query: KnowledgeAdminQuery,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.admin(scope, query),
    queryFn: () => api.listAdminSpaces(query),
    enabled: canQuery(scope) && scope.view === "admin",
    keepPreviousData: false,
  });
}
export function useKnowledgeProcessingSettings(
  scope: KnowledgeQueryScope,
  spaceId: number,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.settings(scope, spaceId),
    queryFn: () => api.getProcessingSettings(spaceId),
    enabled: canQuery(scope, spaceId),
    keepPreviousData: false,
  });
}
export function useKnowledgeProcessingJobs(
  scope: KnowledgeQueryScope,
  spaceId: number,
  query: ProcessingJobsQuery,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.jobs(scope, spaceId, query),
    queryFn: () => api.listProcessingJobs(spaceId, query),
    enabled: canQuery(scope, spaceId),
    keepPreviousData: false,
  });
}
export function useKnowledgeProcessingJob(
  scope: KnowledgeQueryScope,
  spaceId: number,
  jobId: string,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.job(scope, spaceId, jobId),
    queryFn: () => api.getProcessingJob(spaceId, jobId),
    enabled: canQuery(scope, spaceId) && Boolean(jobId),
    keepPreviousData: false,
  });
}
export function useKnowledgeProcessingItems(
  scope: KnowledgeQueryScope,
  spaceId: number,
  jobId: string,
  query: ProcessingItemsQuery,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  useKnowledgeScope(scope);
  return useQuery({
    queryKey: knowledgeQueryKeys.items(scope, spaceId, jobId, query),
    queryFn: () => api.listProcessingItems(spaceId, jobId, query),
    enabled: canQuery(scope, spaceId) && Boolean(jobId),
    keepPreviousData: false,
  });
}

function scopeChanged(
  code: "knowledge_scope_changed" | "knowledge_confirmation_scope_changed",
) {
  return Object.assign(new Error(code), { code });
}

/** Plans are held only for this mounted scope; the server remains the authority. */
export function useKnowledgeProcessingActions(
  scope: KnowledgeQueryScope,
  spaceId: number,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
) {
  const { client, current, stableScope } = useKnowledgeScope(scope);
  const epoch = useMemo(
    () => ({ scope: current, spaceId, api }),
    [current, spaceId, api],
  );
  const latest = useRef(epoch);
  latest.current = epoch;
  return useMemo(() => {
    const plans = new Map<string, string>();
    const assertCurrent = () => {
      if (latest.current !== epoch || !canQuery(stableScope, spaceId))
        throw scopeChanged("knowledge_scope_changed");
    };
    const invalidate = () =>
      client.invalidateQueries({
        queryKey: knowledgeQueryKeys.space(stableScope, spaceId),
      });
    return {
      async precheck(request: ProcessingPrecheckRequest) {
        assertCurrent();
        const result = await api.precheckProcessing(spaceId, request);
        assertCurrent();
        if (result.check_complete && result.can_execute)
          plans.set(result.confirmation_id, result.plan_digest);
        else plans.delete(result.confirmation_id);
        return result;
      },
      async updateSettings(request: ProcessingSettingsWrite) {
        assertCurrent();
        const result = await api.updateProcessingSettings(spaceId, request);
        assertCurrent();
        await invalidate();
        assertCurrent();
        return result;
      },
      async createJob(request: ProcessingCreateRequest) {
        assertCurrent();
        if (plans.get(request.confirmation_id) !== request.plan_digest)
          throw scopeChanged("knowledge_confirmation_scope_changed");
        const result = await api.createProcessingJob(spaceId, request);
        assertCurrent();
        await invalidate();
        assertCurrent();
        return result;
      },
      async retryJob(jobId: string, request: ProcessingRetryRequest) {
        assertCurrent();
        const result = await api.retryProcessingJob(spaceId, jobId, request);
        assertCurrent();
        await invalidate();
        assertCurrent();
        return result;
      },
    };
  }, [api, client, epoch, stableScope, spaceId]);
}
