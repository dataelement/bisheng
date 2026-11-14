import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthContext } from "~/hooks";
import {
  readDeletionTenant,
  precheckDeletion,
  confirmDeletion,
  getDeletionStatus,
  inspectReferences,
  pageReferences,
  type DeleteCommand,
  type DeletePrecheck,
  type ReferenceInspection,
  type ReferencePage,
  type DeletionStatus,
} from "~/api/knowledgeDeletion";

export type KnowledgeDeletionView = {
  command: DeleteCommand;
  readonly: boolean;
  busy: boolean;
  force: boolean;
  dispatched: boolean;
  result?: DeletePrecheck;
  inspection?: ReferenceInspection;
  page?: ReferencePage;
  error?: string;
  code?: number;
  stale?: boolean;
  status?: DeletionStatus;
};
type Entry = {
  command: DeleteCommand;
  scope: string;
  pin: string | null;
  readonly: boolean;
  force: boolean;
  dispatched: boolean;
  result?: DeletePrecheck;
  settle: (success: boolean) => void;
};
export function useKnowledgeDeletion(targetKey: string) {
  const { user } = useAuthContext();
  const scopeKey = JSON.stringify([user?.id, user?.role, targetKey]);
  const latest = useRef(scopeKey);
  latest.current = scopeKey;
  const current = useRef<Entry | null>(null);
  const busy = useRef(false);
  const [view, setView] = useState<KnowledgeDeletionView | null>(null);
  const finish = useCallback((success = false) => {
    const entry = current.current;
    current.current = null;
    busy.current = false;
    setView(null);
    entry?.settle(success);
  }, []);
  const valid = (entry: Entry) => {
    if (current.current !== entry) return false;
    if (latest.current !== entry.scope) {
      finish();
      return false;
    }
    return true;
  };
  useEffect(() => {
    if (current.current?.scope !== scopeKey) finish();
  }, [scopeKey, finish]);
  useEffect(
    () => () => {
      current.current?.settle(false);
      current.current = null;
    },
    [],
  );
  const fail = (entry: Entry, error: unknown) => {
    if (!valid(entry)) return;
    const code =
      error &&
      typeof error === "object" &&
      "status_code" in error &&
      typeof error.status_code === "number"
        ? error.status_code
        : undefined;
    if (code === 19704 || code === 19703) {
      finish();
      return;
    }
    const stale = code === 18087 || code === 18088 || code === 10996;
    if (code === 18087 || code === 18088 || (code === 10996 && !entry.dispatched)) {
      entry.result = undefined;
      entry.dispatched = false;
      entry.force = false;
    }
    setView(
      (old) =>
        old && {
          ...old,
          busy: false,
          error: error instanceof Error ? error.message : undefined,
          code,
          stale,
          dispatched: entry.dispatched,
          ...(entry.result ? {} : { result: undefined }),
        },
    );
  };
  const load = async (entry: Entry) => {
    if (!valid(entry) || busy.current || entry.dispatched) return;
    busy.current = true;
    setView({
      command: entry.command,
      readonly: entry.readonly,
      busy: true,
      force: entry.force,
      dispatched: false,
    });
    try {
      let initial: ReferenceInspection | undefined;
      if (entry.pin === null) {
        const captured = await readDeletionTenant(entry.command);
        if (!valid(entry)) return;
        entry.pin = captured.tenant;
        initial = captured.inspection;
      }
      if (entry.readonly) {
        const inspection =
          initial ?? (await inspectReferences(entry.command, entry.pin ?? undefined));
        if (valid(entry))
          setView({
            command: entry.command,
            readonly: true,
            inspection,
            page: inspection.source_page,
            busy: false,
            force: false,
            dispatched: false,
          });
      } else {
        const result = await precheckDeletion(entry.command, entry.force, entry.pin ?? undefined);
        if (!valid(entry)) return;
        entry.result = result;
        setView({
          command: entry.command,
          readonly: false,
          result,
          page: result.impact.source_page,
          busy: false,
          force: entry.force,
          dispatched: false,
        });
      }
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) busy.current = false;
    }
  };
  const open = (command: DeleteCommand, readonly = false): Promise<boolean> => {
    if (current.current) return Promise.resolve(false);
    if (
      !Number.isSafeInteger(command.spaceId) ||
      command.spaceId <= 0 ||
      (command.kind === "files" &&
        (!command.items?.length ||
          command.items.some((item) => !Number.isSafeInteger(item.id) || item.id <= 0)))
    )
      return Promise.resolve(false);
    return new Promise((resolve) => {
      const snapshot = Object.freeze({
        ...command,
        ...(command.items
          ? { items: Object.freeze(command.items.map((item) => Object.freeze({ ...item }))) }
          : {}),
      });
      const entry: Entry = {
        command: snapshot,
        scope: latest.current,
        pin: null,
        readonly,
        force: false,
        dispatched: false,
        settle: resolve,
      };
      current.current = entry;
      void load(entry);
    });
  };
  const applyStatus = (entry: Entry, status: DeletionStatus) => {
    if (!valid(entry)) return;
    if (status.state === "succeeded") finish(true);
    else
      setView((old) => old && { ...old, status, busy: false, error: undefined, code: undefined });
  };
  const confirm = async (skip: boolean, danger: boolean) => {
    const entry = current.current;
    if (
      !entry ||
      !valid(entry) ||
      busy.current ||
      entry.readonly ||
      !entry.result ||
      !entry.result.check_complete ||
      !entry.result.can_execute ||
      (entry.result.requires_skip_confirmation && !skip) ||
      (entry.force && !danger) ||
      view?.stale
    )
      return;
    busy.current = true;
    entry.dispatched = true;
    setView((old) => old && { ...old, busy: true, dispatched: true, error: undefined });
    try {
      const result = await confirmDeletion(
        entry.command.spaceId,
        {
          confirmation_id: entry.result.confirmation_id,
          plan_digest: entry.result.plan_digest,
          idempotency_key: `delete:${entry.result.confirmation_id}`,
        },
        entry.pin ?? undefined,
      );
      applyStatus(entry, result);
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) {
        busy.current = false;
        setView((old) => old && { ...old, busy: false });
      }
    }
  };
  const status = async () => {
    const entry = current.current;
    if (!entry?.result || !entry.dispatched || !valid(entry) || busy.current) return;
    busy.current = true;
    setView((old) => old && { ...old, busy: true });
    try {
      applyStatus(
        entry,
        await getDeletionStatus(
          entry.command.spaceId,
          entry.result.confirmation_id,
          entry.pin ?? undefined,
        ),
      );
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) {
        busy.current = false;
        setView((old) => old && { ...old, busy: false });
      }
    }
  };
  const more = async () => {
    const entry = current.current;
    const cursor = view?.page?.next_cursor;
    if (!entry || !cursor || !valid(entry) || busy.current || view?.stale) return;
    busy.current = true;
    setView((old) => old && { ...old, busy: true });
    try {
      const page = await pageReferences(entry.command, cursor, entry.pin ?? undefined);
      if (valid(entry))
        setView(
          (old) =>
            old && {
              ...old,
              busy: false,
              page: { ...page, data: [...(old.page?.data ?? []), ...page.data] },
            },
        );
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) busy.current = false;
    }
  };
  const force = () => {
    const entry = current.current;
    if (
      !entry ||
      !valid(entry) ||
      busy.current ||
      entry.dispatched ||
      entry.readonly ||
      entry.command.kind !== "delete" ||
      !entry.result?.check_complete ||
      view?.code === 10994
    )
      return;
    entry.force = true;
    entry.result = undefined;
    void load(entry);
  };
  const refresh = () => {
    const entry = current.current;
    if (entry && !entry.dispatched) {
      entry.result = undefined;
      entry.force = false;
      void load(entry);
    }
  };
  return {
    view,
    open,
    confirm,
    force,
    status,
    more,
    refresh,
    cancel: () => {
      if (!busy.current && !current.current?.dispatched) finish();
    },
  };
}
