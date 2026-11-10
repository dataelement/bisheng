import { showApiError } from "@/controllers/request";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  inspectBatch,
  precheckBatch,
  confirmBatch,
  type BatchCommand,
  type BatchResult,
  type BatchItem,
} from "@/controllers/API/knowledgeBatch";
import type { OperationPrecheck } from "@/controllers/API/knowledgeSpace";
import { managementRequestScope } from "@/controllers/managementScope";
export type BatchView = {
  command: BatchCommand;
  busy: boolean;
  result?: OperationPrecheck;
  outcome?: BatchResult;
  error?: string;
  stale?: boolean;
  dispatched: boolean;
  localInvalid: BatchItem[];
};
type Entry = {
  command: BatchCommand;
  scope: string;
  pin?: string;
  result?: OperationPrecheck;
  dispatched: boolean;
  localInvalid: BatchItem[];
  resolve: (result: BatchResult | null) => void;
};
export function useKnowledgeBatch(targetKey: string) {
  const scopeKey = targetKey;
  const latest = useRef(scopeKey);
  latest.current = scopeKey;
  const entry = useRef<Entry | null>(null),
    locked = useRef(false);
  const [view, setView] = useState<BatchView | null>(null);
  const finish = useCallback((outcome: BatchResult | null = null) => {
    const current = entry.current;
    entry.current = null;
    locked.current = false;
    setView(null);
    current?.resolve(outcome);
  }, []);
  const valid = (current: Entry) => {
    if (entry.current !== current) return false;
    if (
      latest.current !== current.scope ||
      (current.pin !== undefined && String(managementRequestScope()) !== current.pin)
    ) {
      finish();
      return false;
    }
    return true;
  };
  useEffect(() => {
    if (entry.current && entry.current.scope !== scopeKey) finish();
  }, [scopeKey, finish]);
  useEffect(
    () => () => {
      entry.current?.resolve(null);
      entry.current = null;
    },
    [],
  );
  const fail = (current: Entry, error: unknown) => {
    if (!valid(current)) return;
    const code =
      error && typeof error === "object" && "status_code" in error ? error.status_code : undefined;
    const normalized = showApiError(error);
    const stale = code === 18087 || code === 18088 || code === 19704 || code === 19703;
    if (stale) {
      current.result = undefined;
      current.dispatched = false;
    }
    setView(
      (old) =>
        old && {
          ...old,
          busy: false,
          error:
            normalized.kind === "canceled" || normalized.presentation === "global"
              ? undefined
              : normalized.message,
          stale,
          dispatched: current.dispatched,
          ...(stale ? { result: undefined, outcome: undefined } : {}),
        },
    );
  };
  const review = async (current: Entry) => {
    if (!valid(current) || locked.current || current.dispatched || !current.command.items.length)
      return;
    locked.current = true;
    setView({
      command: current.command,
      busy: true,
      dispatched: false,
      localInvalid: current.localInvalid,
    });
    try {
      const inspected = await inspectBatch(current.command);
      if (!valid(current)) return;
      current.pin = inspected.tenant;
      const result = await precheckBatch(current.command, current.pin);
      if (!valid(current)) return;
      current.result = result;
      setView({
        command: current.command,
        result,
        busy: false,
        dispatched: false,
        localInvalid: current.localInvalid,
      });
    } catch (error) {
      fail(current, error);
    } finally {
      if (entry.current === current) locked.current = false;
    }
  };
  const open = (command: BatchCommand): Promise<BatchResult | null> => {
    if (entry.current) return Promise.resolve(null);
    const localInvalid = command.items.filter(
      (item) => !Number.isSafeInteger(item.id) || item.id <= 0,
    );
    const concrete = command.items.filter((item) => Number.isSafeInteger(item.id) && item.id > 0);
    const snapshot: BatchCommand = {
      ...command,
      items: concrete.map((item) => ({ ...item })),
      ...(command.tag_ids ? { tag_ids: [...command.tag_ids] } : {}),
      ...(command.new_tag_names ? { new_tag_names: [...command.new_tag_names] } : {}),
    };
    return new Promise((resolve) => {
      const current: Entry = {
        command: snapshot,
        scope: latest.current,
        dispatched: false,
        localInvalid,
        resolve,
      };
      entry.current = current;
      setView({ command: snapshot, busy: false, dispatched: false, localInvalid });
      void review(current);
    });
  };
  const confirm = async (skip: boolean) => {
    const current = entry.current;
    if (
      !current ||
      !valid(current) ||
      locked.current ||
      !current.result?.can_execute ||
      !current.result.check_complete ||
      ((current.result.requires_skip_confirmation || current.localInvalid.length > 0) && !skip)
    )
      return;
    locked.current = true;
    current.dispatched = true;
    setView((old) => old && { ...old, busy: true, dispatched: true, error: undefined });
    try {
      const outcome = await confirmBatch(
        current.command,
        {
          confirmation_id: current.result.confirmation_id,
          plan_digest: current.result.plan_digest,
          idempotency_key: `batch:${current.result.confirmation_id}`,
        },
        current.pin!,
      );
      if (valid(current)) setView((old) => old && { ...old, outcome, busy: false });
    } catch (error) {
      fail(current, error);
    } finally {
      if (entry.current === current) {
        locked.current = false;
        setView((old) => old && { ...old, busy: false });
      }
    }
  };
  const canClose = () =>
    !locked.current &&
    (!entry.current?.dispatched ||
      (!!view?.outcome && !view.outcome.items.some((item) => item.state === "pending_dispatch")));
  return {
    view,
    open,
    confirm,
    review: () => {
      if (entry.current) void review(entry.current);
    },
    close: () => {
      if (canClose()) finish(view?.outcome ?? null);
    },
  };
}
