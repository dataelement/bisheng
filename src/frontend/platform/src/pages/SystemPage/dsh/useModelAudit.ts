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

export function useModelAudit(
  query: ModelAuditQuery,
  revision: number,
  groupKey?: string,
  enabled = true,
) {
  const [page, setPage] = useState<ModelAuditPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [missing, setMissing] = useState<MissingModelAudit | null>(null);
  useEffect(() => {
    if (!enabled) {
      setPage(null);
      setLoading(false);
      setFailed(false);
      setMissing(null);
      return;
    }
    const controller = new AbortController();
    setPage(null);
    setLoading(true);
    setFailed(false);
    setMissing(null);
    (groupKey
      ? getAuditGroupRequests(groupKey, query, controller.signal)
      : getModelAudit(query, controller.signal)
    )
      .then(async (value) => {
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
          if (!controller.signal.aborted && "audit_record_missing" in detail)
            setMissing(detail);
        }
        if (!controller.signal.aborted) {
          setPage(value);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setFailed(true);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [query, revision, groupKey, enabled]);
  return { page, loading, failed, missing };
}
