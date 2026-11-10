import {
  getModelAudit,
  getModelAuditDetail,
  getAuditGroupRequests,
} from "@/controllers/API/dshModelAudit";
import type {
  ModelAuditPage,
  ModelAuditQuery,
  MissingModelAudit,
} from "@/types/dshModelAudit";
import { useEffect, useState } from "react";

type AuditRequestState = {
  query: ModelAuditQuery;
  revision: number;
  groupKey?: string;
  page: ModelAuditPage | null;
  loading: boolean;
  failed: boolean;
  missing: MissingModelAudit | null;
};

export function useModelAudit(
  query: ModelAuditQuery,
  revision: number,
  groupKey?: string,
  enabled = true,
) {
  const [result, setResult] = useState<AuditRequestState | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const scope = { query, revision, groupKey };
    setResult({
      ...scope,
      page: null,
      loading: true,
      failed: false,
      missing: null,
    });
    (groupKey
      ? getAuditGroupRequests(groupKey, query, controller.signal)
      : getModelAudit(query, controller.signal)
    )
      .then(async (value) => {
        let missing: MissingModelAudit | null = null;
        if (
          query.request_id &&
          !value.items.length &&
          !controller.signal.aborted
        ) {
          const detail = await getModelAuditDetail(
            query.request_id,
            query.tenant_id,
            controller.signal,
          );
          if ("audit_record_missing" in detail) missing = detail;
        }
        if (!controller.signal.aborted) {
          // Preserve absent safety observations and nullable model facts exactly as returned.
          setResult({
            ...scope,
            page: value,
            loading: false,
            failed: false,
            missing,
          });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setResult({
            ...scope,
            page: null,
            loading: false,
            failed: true,
            missing: null,
          });
        }
      });
    return () => controller.abort();
  }, [query, revision, groupKey, enabled]);
  // A new filter, tenant or refresh must not expose the previous request's page
  // during the render before its effect starts. Older transports may ignore abort.
  const current =
    enabled &&
    result?.query === query &&
    result.revision === revision &&
    result.groupKey === groupKey;
  return {
    page: current ? result.page : null,
    loading: enabled && (!current || result.loading),
    failed: current ? result.failed : false,
    missing: current ? result.missing : null,
  };
}
