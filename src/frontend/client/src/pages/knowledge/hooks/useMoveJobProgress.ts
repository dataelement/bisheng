import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  getProcessingJob,
  listProcessingItems,
  listProcessingJobs,
  retryProcessingJob,
  type JobAccepted,
} from "~/api/knowledgeProcessing";
import {
  confirmMoveFilesApi,
  type MoveConfirmation,
  type MovedEntry,
} from "~/api/knowledge";
import { useAuthContext } from "~/hooks/AuthContext";

type PendingConfirmation = {
  review: MoveConfirmation;
  key: string;
  user: string;
  source: string;
};

const storageKey = (user: string, source: string) =>
  `knowledge-move-confirmation:${JSON.stringify([user, source])}`;

function readConfirmation(
  user: string,
  source: string,
): PendingConfirmation | null {
  try {
    const saved = sessionStorage.getItem(storageKey(user, source));
    if (!saved) return null;
    const value = JSON.parse(saved) as PendingConfirmation;
    return value.user === user &&
      value.source === source &&
      typeof value.key === "string" &&
      !!value.key &&
      typeof value.review?.managementTenant === "string" &&
      typeof value.review.precheck?.confirmation_id === "string" &&
      typeof value.review.precheck.plan_digest === "string"
      ? value
      : null;
  } catch (error) {
    // An unavailable browser cache cannot authorize or resume a server operation.
    console.warn("Unable to read pending move confirmation", error);
    return null;
  }
}

export function useMoveJobProgress(
  spaceId: string,
  onMoved: () => void,
  onRecovered?: (entries: MovedEntry[]) => void,
) {
  const { user } = useAuthContext();
  const [operation, setOperation] = useState<{
    id: string;
    tenant: string;
    user: string;
    source: string;
  } | null>(null);
  const userId = user ? String(user.id) : "";
  const [confirmation, setConfirmation] = useState<PendingConfirmation | null>(
    () => readConfirmation(userId, spaceId),
  );
  const pending = useRef(confirmation);
  pending.current = confirmation;
  useEffect(() => {
    const value = readConfirmation(userId, spaceId);
    pending.current = value;
    setConfirmation(value);
  }, [userId, spaceId]);
  const clearConfirmation = () => {
    sessionStorage.removeItem(storageKey(userId, spaceId));
    pending.current = null;
    setConfirmation(null);
  };
  const recovered = useRef(onRecovered);
  recovered.current = onRecovered;
  const [open, setOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState(false);
  const [page, setPage] = useState(1);
  const moved = useRef(onMoved);
  moved.current = onMoved;
  const history = useQuery({
    queryKey: ["knowledge-move-history", user?.id, spaceId, page],
    queryFn: () =>
      listProcessingJobs(Number(spaceId), {
        kind: "move_index",
        page,
        page_size: 20,
      }),
    enabled: open && !operation && !confirmation,
    retry: false,
  });
  const current =
    !!operation && operation.user === userId && operation.source === spaceId;
  const job = useQuery({
    queryKey: [
      "knowledge-move",
      user?.id,
      operation?.tenant,
      spaceId,
      operation?.id,
    ],
    queryFn: () =>
      getProcessingJob(Number(spaceId), operation!.id, "move_index"),
    enabled: current,
    refetchInterval: (result) =>
      result && !["accepted", "running"].includes(result.state) ? false : 2000,
    retry: false,
  });
  const items = useQuery({
    queryKey: [
      "knowledge-move-items",
      user?.id,
      operation?.tenant,
      spaceId,
      operation?.id,
      page,
      job.data?.revision,
    ],
    queryFn: () =>
      listProcessingItems(Number(spaceId), operation!.id, {
        kind: "move_index",
        page,
        page_size: 20,
      }),
    enabled: current && open && !!job.data && !job.error,
    retry: false,
  });
  const completed = useRef<string | null>(null);
  useEffect(() => {
    if (
      current &&
      job.data?.state === "succeeded" &&
      completed.current !== job.data.id
    ) {
      completed.current = job.data.id;
      moved.current();
    }
  }, [current, job.data?.id, job.data?.state]);
  const start = (accepted: JobAccepted, tenant: string) => {
    setOperation({
      id: accepted.job_id,
      tenant,
      user: userId,
      source: spaceId,
    });
    setPage(1);
    setOpen(true);
    setRetryError(false);
  };
  const retry = async () => {
    if (!current || !operation || !job.data?.retryable) return;
    setRetrying(true);
    setRetryError(false);
    try {
      await retryProcessingJob(
        Number(spaceId),
        operation.id,
        {
          idempotency_key: crypto.randomUUID(),
          expected_job_revision: job.data.revision,
        },
        "move_index",
        operation.tenant,
      );
      await job.refetch();
      await items.refetch();
    } catch {
      setRetryError(true);
    } finally {
      setRetrying(false);
    }
  };
  return {
    open: open && !!user && (!operation || current),
    setOpen,
    showHistory: () => {
      setOperation(null);
      setPage(1);
      setOpen(true);
      setRetryError(false);
    },
    start,
    job: job.error ? undefined : job.data,
    items: items.data,
    history: history.data,
    select: async (id: string) => {
      setRetryError(false);
      try {
        const response = await import("~/api/knowledge");
        const tenant = await response.getMoveManagementTenant(spaceId);
        setOperation({ id, tenant, user: userId, source: spaceId });
        setPage(1);
      } catch {
        setRetryError(true);
      }
    },
    error: !!job.error || !!items.error || !!history.error || retryError,
    loading: job.isFetching,
    retrying,
    retry,
    page,
    setPage,
    confirmation: confirmation?.user === String(user?.id) ? confirmation : null,
    remember: (review: MoveConfirmation, key: string) => {
      const value = {
        review: {
          precheck: {
            confirmation_id: review.precheck.confirmation_id,
            plan_digest: review.precheck.plan_digest,
          },
          managementTenant: review.managementTenant,
        },
        key,
        user: userId,
        source: spaceId,
      };
      // Persist only the opaque locator, so reload can replay the original operation.
      sessionStorage.setItem(
        storageKey(userId, spaceId),
        JSON.stringify(value),
      );
      pending.current = value;
      setOperation(null);
      setPage(1);
      setRetryError(false);
      setConfirmation(value);
    },
    hasPendingConfirmation: () =>
      !!pending.current &&
      pending.current.user === userId &&
      pending.current.source === spaceId,
    clearConfirmation,
    recoverConfirmation: () => setOpen(true),
    resumeConfirmation: async () => {
      if (
        !confirmation ||
        confirmation.user !== userId ||
        confirmation.source !== spaceId
      )
        return;
      setRetrying(true);
      setRetryError(false);
      try {
        const result = await confirmMoveFilesApi(
          confirmation.source,
          confirmation.review,
          confirmation.key,
        );
        clearConfirmation();
        if ("accepted" in result)
          start(result, confirmation.review.managementTenant);
        else {
          moved.current();
          recovered.current?.(result.moved);
          setOpen(false);
        }
      } catch (error) {
        if (
          [18087, 18088].includes(
            (error as { status_code?: number })?.status_code ?? 0,
          )
        )
          clearConfirmation();
        setRetryError(true);
      } finally {
        setRetrying(false);
      }
    },
    available: !!user,
    refresh: () => (operation ? job.refetch() : history.refetch()),
  };
}
