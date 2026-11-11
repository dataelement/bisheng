import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { userContext } from "@/contexts/userContext";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import type { User } from "@/types/api/user";
import { useAdminScope } from "./useAdminScope";

export function useKnowledgePageScope() {
  const { user }: { user: Partial<User> | null } = useContext(userContext);
  const isSuper = user?.is_global_super === true;
  const management = useAdminScope({ enabled: isSuper });
  const canManage = isSuper || user?.is_child_admin === true;
  const userId = user?.user_id;
  const tenantId = isSuper
    ? management.scope.scope_tenant_id
    : user?.leaf_tenant_id;
  const epoch = useMemo(
    () => ({ userId, isSuper, tenantId }),
    [userId, isSuper, tenantId],
  );
  const current = useRef<typeof epoch | null>(epoch);
  current.current = epoch;
  const [retryEpoch, setRetryEpoch] = useState<typeof epoch | null>(null);
  const retrying = retryEpoch === epoch;
  useEffect(() => {
    current.current = epoch;
    return () => {
      if (current.current === epoch) current.current = null;
    };
  }, [epoch]);

  const ready =
    Number.isSafeInteger(userId) &&
    userId! > 0 &&
    Number.isSafeInteger(tenantId) &&
    tenantId! > 0 &&
    (!isSuper || !management.loading);
  const scopes = useMemo(() => {
    if (!ready || typeof tenantId !== "number" || typeof userId !== "number")
      return null;
    const base = {
      identityKey: `user:${userId}`,
      tenantId,
      managementTenantId: tenantId,
    };
    return {
      ordinary: { ...base, view: "ordinary" } satisfies KnowledgeQueryScope,
      admin: { ...base, view: "admin" } satisfies KnowledgeQueryScope,
    };
  }, [ready, userId, tenantId]);

  const refresh = management.refresh;
  const retry = useCallback(async (): Promise<void> => {
    if (retrying || current.current !== epoch) return;
    if (!isSuper) {
      window.location.reload();
      return;
    }
    setRetryEpoch(epoch);
    try {
      await refresh();
    } catch (error) {
      if (current.current === epoch) showApiError(error);
    } finally {
      if (current.current === epoch)
        setRetryEpoch((active) => (active === epoch ? null : active));
    }
  }, [retrying, epoch, isSuper, refresh]);

  return {
    scopes,
    isLoading: management.loading || retrying,
    canManage,
    user,
    retry,
  };
}
