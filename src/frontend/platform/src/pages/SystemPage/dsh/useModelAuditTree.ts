import { getAuditTree } from "@/controllers/API/dshModelAudit";
import type { AuditTreePage, ModelAuditQuery } from "@/types/dshModelAudit";
import { useEffect, useState } from "react";

export function useModelAuditTree(
  query: ModelAuditQuery,
  parentKey: string,
  generation: string,
) {
  const [cursor, setCursor] = useState<string>();
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<AuditTreePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const signature = JSON.stringify({ ...query, cursor: undefined });
  useEffect(() => {
    const abort = new AbortController();
    setPage(null);
    setLoading(true);
    setFailed(false);
    const requestQuery: ModelAuditQuery = { ...JSON.parse(signature), cursor };
    getAuditTree(requestQuery, abort.signal, parentKey, generation)
      .then((value) => {
        if (!abort.signal.aborted) setPage(value);
      })
      .catch(() => {
        if (!abort.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [signature, parentKey, generation, cursor, revision]);
  return {
    page,
    loading,
    failed,
    previous: history.length > 0,
    onPrevious: () => {
      setCursor(history[history.length - 1]);
      setHistory((old) => old.slice(0, -1));
    },
    onNext: () => {
      if (page?.next_cursor) {
        setHistory((old) => [...old, cursor]);
        setCursor(page.next_cursor);
      }
    },
    onRetry: () => setRevision((old) => old + 1),
  };
}
