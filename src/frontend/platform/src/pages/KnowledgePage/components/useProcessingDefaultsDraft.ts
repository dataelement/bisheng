import { useQueryClient } from "@tanstack/react-query";
import { isEqual } from "lodash-es";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceApi,
  type ProcessingSettingsRead,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  useKnowledgeProcessingSettings,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import {
  processingDefaultsToDraft,
  validateProcessingDefaultsDraft,
  type ProcessingDefaultsDraft,
} from "./ProcessingDefaultsEditor";

function hasLocalChanges(
  draft: ProcessingDefaultsDraft,
  baseline: ProcessingDefaultsDraft,
) {
  return (
    draft.pendingPattern !== baseline.pendingPattern ||
    !isEqual(draft.document, baseline.document) ||
    !isEqual(draft.table, baseline.table)
  );
}

export function useProcessingDefaultsDraft(
  scope: KnowledgeQueryScope,
  spaceId: number,
  api: KnowledgeSpaceApi = knowledgeSpaceApi,
  enabled = true,
) {
  const client = useQueryClient();
  const query = useKnowledgeProcessingSettings(scope, spaceId, api, enabled);
  const { identityKey, tenantId, managementTenantId, view } = scope;
  const queryKey = useMemo(
    () =>
      knowledgeQueryKeys.settings(
        { identityKey, tenantId, managementTenantId, view },
        spaceId,
      ),
    [identityKey, tenantId, managementTenantId, view, spaceId],
  );
  const epoch = useMemo(
    () => ({ queryKey, api, enabled }),
    [queryKey, api, enabled],
  );
  const current = useRef<typeof epoch | null>(epoch);
  current.current = epoch;
  const saving = useRef<typeof epoch | null>(null);
  const [savingEpoch, setSavingEpoch] = useState<typeof epoch | null>(null);
  const [loaded, setLoaded] = useState<{
    epoch: typeof epoch;
    version: number;
    draft: ProcessingDefaultsDraft;
    baseline: ProcessingDefaultsDraft;
  } | null>(null);
  const refetch = query.refetch;
  // A manual refresh must use the same eligibility as the automatic read.
  const canLoad =
    enabled &&
    Boolean(identityKey) &&
    Number.isSafeInteger(tenantId) &&
    tenantId > 0 &&
    Number.isSafeInteger(spaceId) &&
    spaceId > 0;
  const load = useCallback(async () => {
    if (!canLoad || current.current !== epoch || saving.current === epoch) return;
    try {
      const result = await refetch({ cancelRefetch: false });
      if (
        current.current !== epoch ||
        saving.current === epoch ||
        !result.isSuccess ||
        !result.data
      )
        return;
      const baseline = processingDefaultsToDraft(result.data.effective_defaults);
      const version = result.data.config_version;
      setLoaded((previous) =>
        previous?.epoch === epoch &&
        hasLocalChanges(previous.draft, previous.baseline)
          ? previous
          : { epoch, version, draft: baseline, baseline },
      );
    } catch (error) {
      if (current.current === epoch) showApiError(error);
    }
  }, [canLoad, epoch, refetch]);
  useEffect(() => {
    current.current = epoch;
    setLoaded(null);
    void load();
    return () => {
      if (current.current === epoch) current.current = null;
      // An active observer still owns this read and its cache.
      const retired = client
        .getQueryCache()
        .find({ queryKey: epoch.queryKey, exact: true });
      if (retired?.getObserversCount() === 0)
        void client.cancelQueries({ queryKey: epoch.queryKey, exact: true });
    };
  }, [client, epoch, load]);

  const active = loaded?.epoch === epoch ? loaded : null;
  const draft = active?.draft ?? null;
  const validation = draft ? validateProcessingDefaultsDraft(draft) : null;
  const dirty = active ? hasLocalChanges(active.draft, active.baseline) : false;
  const pending = savingEpoch === epoch;
  const isCurrent = () => current.current === epoch;
  function setDraft(next: ProcessingDefaultsDraft) {
    if (!isCurrent() || saving.current === epoch) return;
    setLoaded((previous) =>
      previous?.epoch === epoch ? { ...previous, draft: next } : previous,
    );
  }
  function reset() {
    if (!isCurrent() || saving.current === epoch) return;
    setLoaded((previous) =>
      previous?.epoch === epoch ? { ...previous, draft: previous.baseline } : previous,
    );
  }
  async function save(): Promise<ProcessingSettingsRead | undefined> {
    if (
      !canLoad ||
      !active ||
      !validation?.ok ||
      saving.current === epoch ||
      !isCurrent()
    )
      throw new Error("Processing defaults are not ready to save");
    saving.current = epoch;
    setSavingEpoch(epoch);
    try {
      const result = await api.updateProcessingSettings(spaceId, {
        expected_config_version: active.version,
        defaults: validation.value,
      });
      if (!isCurrent()) return;
      const baseline = processingDefaultsToDraft(result.effective_defaults);
      // The API has committed the new version. A later refresh cannot undo it.
      setLoaded({
        epoch,
        version: result.config_version,
        draft: baseline,
        baseline,
      });
      await client.invalidateQueries({ queryKey });
      if (isCurrent()) return result;
    } catch (error) {
      if (isCurrent()) throw error;
    } finally {
      if (saving.current === epoch) saving.current = null;
      if (isCurrent()) setSavingEpoch(null);
    }
  }

  return {
    draft,
    dirty,
    valid: validation?.ok === true,
    error: canLoad && query.isError,
    pending,
    isCurrent,
    load,
    setDraft,
    reset,
    save,
  };
}
