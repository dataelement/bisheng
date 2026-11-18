import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  deleteLLMServer,
  listLLMRemovalSources,
  precheckLLMServerDelete,
  precheckLLMServerUpdate,
  snapshotModelUpdate,
  updateLLMServer,
} from "@/controllers/API/llm";
import type {
  LLMServerDraftRequest,
  LLMServerUpsertReq,
  ModelReferencePage,
  ModelRemovalPrecheck,
} from "@/controllers/API/llm";
import { managementRequestScope } from "@/controllers/managementScope";
import { isApiError } from "@bisheng/api-client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  hasDuplicateModelName,
  hasInvalidModelName,
  trimModelNames,
} from "./modelNameTrim";

type Command =
  | { kind: "update"; server: LLMServerUpsertReq }
  | { kind: "delete"; serverId: number };
type Entry = {
  command: Command;
  identityKey: string;
  scope: number | null;
  result?: ModelRemovalPrecheck;
  force: boolean | null;
  dispatched: boolean;
  controller: AbortController;
  settle: (saved: boolean) => void;
};
export type ModelRemovalView = {
  kind: Command["kind"];
  pending: boolean;
  result?: ModelRemovalPrecheck;
  page?: ModelReferencePage;
  error?: string;
  errorCode?: number;
  needsRefresh: boolean;
  dispatched: boolean;
  force: boolean | null;
};
type Options = {
  enabled: boolean;
  identityKey: string;
};

export function prepareModelDraft(models: LLMServerDraftRequest["models"]) {
  const normalized = trimModelNames(models);
  const errorKey =
    hasInvalidModelName(normalized) ||
    normalized.some((model) => !model.model_type)
      ? "model.modelNameValidation"
      : hasDuplicateModelName(normalized)
        ? "model.modelDuplicate"
        : normalized.some(
              (model) => model.model_type === "tts" && !model.config?.voice,
            )
          ? "model.voiceTypeRequired"
          : null;
  return { models: normalized, errorKey };
}

export function useModelRemoval(options: Options) {
  const { t } = useTranslation("model");
  const latest = useRef(options);
  latest.current = options;
  const current = useRef<Entry | null>(null);
  const locked = useRef(false);
  const saving = useRef(false);
  const baselineIds = useRef<number[]>([]);
  const [view, setView] = useState<ModelRemovalView | null>(null);
  const rememberBaseline = useCallback(
    (models: readonly { id?: number | string | null }[]) => {
      baselineIds.current = models.flatMap((model) =>
        typeof model.id === "number" && model.id > 0 ? [model.id] : [],
      );
    },
    [],
  );

  const finish = useCallback((saved: boolean) => {
    const entry = current.current;
    current.current = null;
    locked.current = false;
    setView(null);
    entry?.controller.abort();
    entry?.settle(saved);
  }, []);
  const valid = useCallback(
    (entry: Entry) => {
      const owned = current.current === entry;
      const unchanged =
        owned &&
        latest.current.enabled &&
        latest.current.identityKey === entry.identityKey &&
        managementRequestScope() === entry.scope;
      if (owned && !unchanged) finish(false);
      return unchanged;
    },
    [finish],
  );
  const fail = (entry: Entry, error: unknown) => {
    if (!valid(entry)) return;
    const code = isApiError(error) ? error.status_code : undefined;
    const stale = code === 18087 || code === 18088 || code === 10996;
    if (stale) {
      entry.result = undefined;
      entry.dispatched = false;
      entry.force = null;
    }
    setView(
      (previous) =>
        previous && {
          ...previous,
          pending: false,
          error:
            error instanceof Error
              ? error.message
              : String(t("model.removalFailed")),
          errorCode: code,
          needsRefresh: stale,
          dispatched: entry.dispatched,
          force: entry.force,
          ...(stale ? { result: undefined, page: undefined } : {}),
        },
    );
  };
  const inspect = async (entry: Entry) => {
    if (!valid(entry) || locked.current || entry.dispatched) return;
    entry.controller.abort();
    entry.controller = new AbortController();
    locked.current = true;
    setView(
      (previous) =>
        previous && {
          ...previous,
          pending: true,
          error: undefined,
          errorCode: undefined,
        },
    );
    try {
      const result =
        entry.command.kind === "update"
          ? await precheckLLMServerUpdate(structuredClone(entry.command.server))
          : await precheckLLMServerDelete(entry.command.serverId);
      if (!valid(entry)) return;
      if (
        !result?.inspection?.check_complete ||
        result.inspection.server_id !==
          (entry.command.kind === "update"
            ? entry.command.server.id
            : entry.command.serverId) ||
        result.confirmation.operation !==
          (entry.command.kind === "update"
            ? "model_update_server"
            : "model_delete_server")
      ) {
        throw new Error(String(t("model.removalFailed")));
      }
      entry.result = result;
      setView(
        (previous) =>
          previous && {
            ...previous,
            result,
            page: result.inspection.source_page,
            pending: false,
            needsRefresh: false,
          },
      );
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) locked.current = false;
    }
  };
  const begin = (command: Command) => {
    if (!latest.current.enabled || current.current)
      return Promise.resolve(false);
    return new Promise<boolean>((settle) => {
      const entry: Entry = {
        command,
        identityKey: latest.current.identityKey,
        scope: managementRequestScope(),
        force: null,
        dispatched: false,
        controller: new AbortController(),
        settle,
      };
      current.current = entry;
      setView({
        kind: command.kind,
        pending: true,
        needsRefresh: false,
        dispatched: false,
        force: null,
      });
      void inspect(entry);
    });
  };
  const submit = async (force: boolean) => {
    const entry = current.current;
    if (!entry || !valid(entry) || locked.current || !entry.result) return;
    if (!entry.dispatched && entry.result.inspection.blocked && !force) return;
    locked.current = true;
    entry.force = entry.dispatched ? entry.force : force;
    entry.dispatched = true;
    setView(
      (previous) =>
        previous && {
          ...previous,
          pending: true,
          dispatched: true,
          force: entry.force,
          error: undefined,
        },
    );
    const control = {
      force: entry.force === true,
      confirmation_id: entry.result.confirmation.confirmation_id,
      plan_digest: entry.result.confirmation.plan_digest,
    };
    try {
      if (entry.command.kind === "update")
        await updateLLMServer(structuredClone(entry.command.server), control);
      else await deleteLLMServer(entry.command.serverId, control);
      if (valid(entry)) finish(true);
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) locked.current = false;
    }
  };
  const requestForce = () => {
    const entry = current.current;
    if (
      !entry ||
      !valid(entry) ||
      locked.current ||
      !entry.result ||
      entry.dispatched ||
      !entry.result.inspection.check_complete ||
      view?.needsRefresh ||
      view?.errorCode === 10994
    )
      return;
    const signal = entry.controller.signal;
    const confirmation = entry.result.confirmation;
    bsConfirm({
      title: String(t("model.removalForceTitle")),
      desc: String(t("model.removalForceWarning")),
      okTxt: String(t("model.removalForceConfirm")),
      showClose: false,
      signal,
      async onOk(next) {
        if (signal.aborted || entry.result?.confirmation !== confirmation)
          return;
        await submit(true);
        if (current.current === entry) next();
      },
    });
  };
  const loadMore = async () => {
    const entry = current.current;
    if (
      !entry ||
      !valid(entry) ||
      locked.current ||
      !entry.result ||
      !view?.page?.next_cursor ||
      entry.dispatched
    )
      return;
    locked.current = true;
    const before = view.page;
    setView(
      (previous) =>
        previous && { ...previous, pending: true, error: undefined },
    );
    try {
      const page = await listLLMRemovalSources({
        server_id:
          entry.command.kind === "update"
            ? entry.command.server.id!
            : entry.command.serverId,
        retained_model_ids:
          entry.command.kind === "update"
            ? entry.command.server.models.flatMap((model) =>
                typeof model.id === "number" && model.id > 0 ? [model.id] : [],
              )
            : [],
        delete_server: entry.command.kind === "delete",
        page_size: before.page_size,
        cursor: before.next_cursor!,
      });
      if (valid(entry))
        setView(
          (previous) =>
            previous && {
              ...previous,
              pending: false,
              page: { ...page, data: [...before.data, ...page.data] },
            },
        );
    } catch (error) {
      fail(entry, error);
    } finally {
      if (current.current === entry) locked.current = false;
    }
  };

  useEffect(() => {
    const invalidate = () => finish(false);
    window.addEventListener("bisheng:management-scope-changed", invalidate);
    return () => {
      window.removeEventListener(
        "bisheng:management-scope-changed",
        invalidate,
      );
      invalidate();
    };
    // The owned operation uses refs so cleanup never captures a replacement request.
  }, [finish]);
  useEffect(() => {
    const entry = current.current;
    if (entry) valid(entry);
  }, [options.enabled, options.identityKey, valid]);

  return {
    view,
    active: view !== null,
    rememberBaseline,
    async saveUpdate(
      draft: LLMServerDraftRequest,
      originalUpdate: (server: LLMServerUpsertReq) => Promise<unknown>,
    ) {
      if (!latest.current.enabled || saving.current || current.current)
        return false;
      saving.current = true;
      const snapshot = snapshotModelUpdate(draft);
      const retained = new Set(
        snapshot.models.flatMap((model) =>
          typeof model.id === "number" && model.id > 0 ? [model.id] : [],
        ),
      );
      try {
        if (baselineIds.current.some((id) => !retained.has(id)))
          return await begin({ kind: "update", server: snapshot });
        try {
          await originalUpdate(structuredClone(snapshot));
          return true;
        } catch (error) {
          if (isApiError(error) && error.status_code === 10995)
            return await begin({ kind: "update", server: snapshot });
          throw error;
        }
      } finally {
        saving.current = false;
      }
    },
    requestUpdate: (draft: LLMServerDraftRequest) =>
      saving.current
        ? Promise.resolve(false)
        : begin({ kind: "update", server: snapshotModelUpdate(draft) }),
    requestDelete: (serverId: number) =>
      saving.current
        ? Promise.resolve(false)
        : begin({ kind: "delete", serverId }),
    cancel: () => {
      if (!locked.current && !current.current?.dispatched) finish(false);
    },
    refresh: () => {
      if (current.current) void inspect(current.current);
    },
    confirm: () => {
      void submit(current.current?.force === true);
    },
    requestForce,
    loadMore,
  };
}
