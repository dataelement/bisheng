import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  getProcessingJob,
  knowledgeProcessingKeys,
  listProcessingItems,
  listProcessingJobs,
  retryProcessingJob,
  type PageData,
  type ProcessingIdentityScope,
  type ProcessingJobRead,
  type ProcessingKind,
  type ProcessingRetryRequest,
} from "~/api/knowledgeProcessing";
import { showApiError } from "~/api/request";
import { generateUUID } from "~/utils";
import { useAuthContext } from "~/hooks/AuthContext";

export const ordinaryProcessingKinds = [
  "embedding_rebuild",
  "file_reprocess",
  "file_resplit",
  "metadata_schema_change",
] as const;
type OrdinaryKind = (typeof ordinaryProcessingKinds)[number];
const ordinary = (kind: ProcessingKind): kind is OrdinaryKind =>
  ordinaryProcessingKinds.some((value) => value === kind);
const running = (job: ProcessingJobRead) => job.state === "accepted" || job.state === "running";
type Selected = { id: string; kind: OrdinaryKind };
type Epoch = { id: number; retired: boolean };
type Pending = { target: Selected; command: ProcessingRetryRequest };
type View = {
  epoch: Epoch;
  open: boolean;
  bootstrap: boolean;
  page: number;
  itemPage: number;
  session?: { tenant: string; first: PageData<ProcessingJobRead>; nonce: number };
  selected?: Selected;
  pending?: Pending;
  retrying?: boolean;
  error?: boolean;
  accepted?: boolean;
};

export function useSpaceProcessingJobs(spaceId: string, canEdit: boolean) {
  const { user, token } = useAuthContext();
  const sequence = useRef(0);
  const instance = useId();
  // The credential is only an in-memory lifetime dependency, never a cache key.
  const epoch = useMemo<Epoch>(
    () => ({ id: ++sequence.current, retired: false }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Scope and credential changes intentionally retire every task read.
    [spaceId, canEdit, user?.id, user?.role, token],
  );
  const current = useRef(epoch);
  current.current = epoch;
  const [stored, setStored] = useState<View>();
  const view = stored?.epoch === epoch && !epoch.retired && canEdit && user ? stored : undefined;
  const bootstrap = useRef<AbortController>();
  const busy = useRef(false);
  const valid = () => current.current === epoch && !epoch.retired;
  const update = (change: Partial<View>) => {
    if (valid())
      setStored((previous) => (previous?.epoch === epoch ? { ...previous, ...change } : previous));
  };
  useEffect(() => {
    epoch.retired = false;
    busy.current = false;
    return () => {
      epoch.retired = true;
      bootstrap.current?.abort();
    };
  }, [epoch]);
  const session = view?.session,
    selected = view?.selected;
  const scope: ProcessingIdentityScope = {
    userId: user?.id ?? "",
    tenantId: session?.tenant ?? "unresolved",
    view: "ordinary",
  };
  const page = view?.page ?? 1,
    itemPage = view?.itemPage ?? 1;
  const reads = !!view?.open && !!session;
  const list = useQuery({
    queryKey: [
      ...knowledgeProcessingKeys.jobs(scope, Number(spaceId), { page, page_size: 20 }),
      "client-panel",
      instance,
      epoch.id,
      session?.nonce,
    ],
    queryFn: ({ signal }) =>
      listProcessingJobs(
        Number(spaceId),
        { page, page_size: 20 },
        { tenant: session!.tenant, signal },
      ),
    initialData: page === 1 ? session?.first : undefined,
    enabled: reads && !selected,
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (data) => (data?.data.some(running) ? 2000 : false),
  });
  const job = useQuery({
    queryKey: [
      ...knowledgeProcessingKeys.job(scope, Number(spaceId), selected?.id ?? ""),
      selected?.kind,
      "client-panel",
      instance,
      epoch.id,
      session?.nonce,
    ],
    queryFn: async ({ signal }) => {
      const result = await getProcessingJob(Number(spaceId), selected!.id, selected!.kind, {
        tenant: session!.tenant,
        signal,
      });
      if (
        result.space_id !== Number(spaceId) ||
        result.id !== selected!.id ||
        result.kind !== selected!.kind
      )
        throw new Error("Invalid processing task response");
      return result;
    },
    enabled: reads && !!selected,
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (data) => (data && running(data) ? 2000 : false),
  });
  const items = useQuery({
    queryKey: [
      ...knowledgeProcessingKeys.items(scope, Number(spaceId), selected?.id ?? "", {
        kind: selected?.kind,
        page: itemPage,
        page_size: 20,
      }),
      "client-panel",
      instance,
      epoch.id,
      session?.nonce,
      job.data?.revision,
    ],
    queryFn: ({ signal }) =>
      listProcessingItems(
        Number(spaceId),
        selected!.id,
        { kind: selected!.kind, page: itemPage, page_size: 20 },
        { tenant: session!.tenant, signal },
      ),
    enabled: reads && !!selected && !!job.data && !job.error,
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
  });
  const readError = selected ? job.error || items.error : list.error;
  useEffect(() => {
    if (!readError || current.current !== epoch || epoch.retired) return;
    showApiError(readError);
    if ((readError as { status_code?: number }).status_code === 19704) setStored(undefined);
  }, [readError, epoch]);
  const open = async () => {
    if (!canEdit || !user || !valid() || busy.current) return;
    if (view?.session) {
      update({ open: true });
      return;
    }
    busy.current = true;
    setStored({ epoch, open: true, bootstrap: true, page: 1, itemPage: 1 });
    const controller = new AbortController();
    bootstrap.current = controller;
    let tenant: string | undefined;
    try {
      const first = await listProcessingJobs(
        Number(spaceId),
        { page: 1, page_size: 20 },
        {
          signal: controller.signal,
          onTenant: (actual) => {
            tenant = actual;
          },
        },
      );
      if (!valid()) return;
      if (!tenant) throw new Error("Missing processing task tenant");
      update({
        bootstrap: false,
        session: { tenant, first, nonce: ++sequence.current },
        error: false,
      });
    } catch (error) {
      if (valid()) {
        showApiError(error);
        update({ bootstrap: false, error: true });
      }
    } finally {
      if (valid()) busy.current = false;
    }
  };
  const retry = async () => {
    if (
      !valid() ||
      !canEdit ||
      busy.current ||
      !session ||
      !selected ||
      !job.data ||
      job.error ||
      job.isFetching ||
      (view?.error && !view.pending)
    )
      return;
    const pending =
      view?.pending ??
      (job.data.retryable && {
        target: selected,
        command: { idempotency_key: generateUUID(32), expected_job_revision: job.data.revision },
      });
    if (!pending || pending.target.id !== selected.id || pending.target.kind !== selected.kind)
      return;
    busy.current = true;
    update({ pending, retrying: true, error: false, accepted: false });
    try {
      const accepted = await retryProcessingJob(
        Number(spaceId),
        pending.target.id,
        pending.command,
        pending.target.kind,
        session.tenant,
        { tenant: session.tenant },
      );
      if (!valid()) return;
      if (accepted.job_id !== selected.id || accepted.accepted !== true)
        throw new Error("Invalid processing acknowledgement");
      update({ pending: undefined, accepted: true });
      await job.refetch();
      if (valid()) await items.refetch();
    } catch (error) {
      if (!valid()) return;
      const normalized = showApiError(error);
      const code = (error as { status_code?: number })?.status_code;
      if (code === 19704 || code === 19703) {
        setStored(undefined);
        return;
      }
      // A known business rejection has no ambiguous ACK. Transport failures
      // retain the exact revision/key for an explicit retry of the request.
      update({
        error: true,
        ...(normalized.kind === "business" ||
        (normalized.kind === "http" && normalized.httpStatus && normalized.httpStatus < 500)
          ? { pending: undefined }
          : {}),
      });
    } finally {
      if (valid()) {
        busy.current = false;
        update({ retrying: false });
      }
    }
  };
  return {
    available: canEdit && !!user,
    open: !!view?.open,
    show: open,
    close: () => {
      if (!view?.pending && !view?.retrying) update({ open: false });
    },
    loading: !!view?.bootstrap || (selected ? job.isFetching : list.isFetching),
    history:
      view?.session && !list.error
        ? list.data?.data.filter((row) => row.space_id === Number(spaceId) && ordinary(row.kind))
        : undefined,
    total: list.data?.total ?? 0,
    job: reads && selected && !job.error ? job.data : undefined,
    items: reads && selected && !job.error && !items.error ? items.data : undefined,
    page,
    itemPage,
    setPage: (value: number) => update({ page: value }),
    setItemPage: (value: number) => update({ itemPage: value }),
    select: (entry: ProcessingJobRead) => {
      if (!view?.pending && ordinary(entry.kind))
        update({
          selected: { id: entry.id, kind: entry.kind },
          itemPage: 1,
          error: false,
          accepted: false,
        });
    },
    historyView: () => {
      if (!view?.pending) update({ selected: undefined, error: false, accepted: false });
    },
    selected: !!selected,
    error: !!view?.error || !!readError,
    pending: !!view?.pending,
    retrying: !!view?.retrying,
    accepted: !!view?.accepted,
    retry,
    refresh: async () => {
      if (!session) {
        await open();
        return;
      }
      update({ error: false });
      if (selected) {
        await job.refetch();
        if (valid()) await items.refetch();
      } else await list.refetch();
    },
  };
}
