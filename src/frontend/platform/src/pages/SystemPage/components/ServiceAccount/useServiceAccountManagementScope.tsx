import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getServiceAccountManagementScopeApi,
  setServiceAccountManagementScopeApi,
  type ServiceAccountRequestScope,
} from "@/controllers/API/serviceAccount";
import { getTenantsApi } from "@/controllers/API/tenant";
import { showApiError } from "@/controllers/request";
import type { Tenant } from "@/types/api/tenant";

export const ServiceAccountRequestScopeContext =
  createContext<ServiceAccountRequestScope | null>(null);

export function useServiceAccountRequestScope(): ServiceAccountRequestScope {
  const value = useContext(ServiceAccountRequestScopeContext);
  if (!value)
    throw new Error("Service account view requires an admitted scope");
  return value;
}

/** Exhaust the existing paginated API; never silently hide tenants after page one. */
export async function loadActiveServiceAccountTenants(): Promise<Tenant[]> {
  const result: Tenant[] = [];
  let consumed = 0;
  for (let page = 1; ; page++) {
    const response = await getTenantsApi({
      page,
      page_size: 100,
      status: "active",
    });
    const rows = response.data ?? [];
    result.push(
      ...rows.filter(
        (row) =>
          Number.isInteger(row.id) && row.id > 0 && row.status === "active",
      ),
    );
    consumed += rows.length;
    if (consumed >= response.total)
      return [...new Map(result.map((row) => [row.id, row])).values()];
    if (!rows.length)
      throw new Error("Tenant pagination returned an incomplete page");
  }
}

interface ManagementScopeOptions {
  enabled: boolean;
  userId: number;
  tenantId: number;
}

export function useServiceAccountManagementScope({
  enabled,
  userId,
  tenantId,
}: ManagementScopeOptions) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(
    () => ["service-account-management-scope", userId],
    [userId],
  );
  const [switching, setSwitching] = useState(false);
  const busy = useRef(false);
  const scope = useQuery({
    queryKey,
    queryFn: getServiceAccountManagementScopeApi,
    enabled: enabled && !switching,
    retry: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
  const { refetch } = scope;
  const [refreshRequired, setRefreshRequired] = useState(false);
  const [revision, setRevision] = useState(0);
  const currentTenantId = enabled
    ? (scope.data?.scope_tenant_id ?? null)
    : tenantId;
  const controller = useMemo(
    () => ({
      key: `${userId}:${currentTenantId}:${revision}`,
      value: new AbortController(),
    }),
    [currentTenantId, userId, revision],
  ).value;
  useEffect(() => {
    // React may replay setup after cleanup in development StrictMode.
    if (controller.signal.aborted) setRevision(value => value + 1);
    return () => controller.abort();
  }, [controller]);

  const handleScopeChanged = useCallback(() => {
    controller.abort();
    setRefreshRequired(true);
    // No mutation is replayed. A deliberate refresh is required before editing again.
    void refetch();
  }, [controller, refetch]);
  const requestScope = useMemo<ServiceAccountRequestScope | null>(
    () =>
      currentTenantId == null
        ? null
        : {
            tenantId: currentTenantId,
            signal: controller.signal,
            onScopeChanged: handleScopeChanged,
          },
    [currentTenantId, controller, handleScopeChanged],
  );

  const selectScope = useCallback(
    async (nextTenantId: number) => {
      if (busy.current || !Number.isInteger(nextTenantId) || nextTenantId <= 0)
        return;
      busy.current = true;
      controller.abort();
      setSwitching(true);
      setRevision((value) => value + 1);
      try {
        await queryClient.cancelQueries({ queryKey });
        const result = await setServiceAccountManagementScopeApi(nextTenantId);
        queryClient.setQueryData(queryKey, result);
        setRefreshRequired(false);
      } finally {
        busy.current = false;
        setSwitching(false);
      }
    },
    [controller, queryClient, queryKey],
  );

  const refresh = useCallback(async () => {
    controller.abort();
    setRefreshRequired(true);
    const result = await refetch();
    if (!result.isError) {
      setRevision((value) => value + 1);
      setRefreshRequired(false);
    }
  }, [controller, refetch]);
  const ready =
    !!requestScope &&
    requestScope.tenantId > 0 &&
    !switching &&
    !refreshRequired &&
    (!enabled || (!scope.isLoading && !scope.isError));
  useEffect(() => {
    if (enabled && scope.error) showApiError(scope.error);
  }, [enabled, scope.error]);
  return {
    currentTenantId,
    requestScope,
    ready,
    switching,
    refreshRequired,
    selectScope,
    refresh,
    viewKey: `${userId}:${currentTenantId}:${revision}`,
    loading: enabled && scope.isLoading,
  };
}
