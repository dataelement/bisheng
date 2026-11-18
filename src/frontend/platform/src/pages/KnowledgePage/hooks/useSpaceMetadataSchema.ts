import { toast } from "@bisheng/ui";
import { isApiError } from "@bisheng/api-client";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { JobState, MetadataSchemaChange, ProcessingCreateRequest } from "@/controllers/API/knowledgeSpace";
import { readMetadataSchema } from "@/controllers/API/knowledgeProcessing";
import { knowledgeQueryKeys, useKnowledgeProcessingActions, useKnowledgeProcessingJobs, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { createDshOperationId } from "@/util/dshOperationId";
import { showApiError } from "@/controllers/request";

interface SpaceMetadataSchemaOptions {
  scope: KnowledgeQueryScope;
  spaceId: number;
  enabled?: boolean;
}
export function useSpaceMetadataSchema({ scope, spaceId, enabled = true }: SpaceMetadataSchemaOptions) {
  const { t } = useTranslation("knowledge");
  const alive = useRef(true),
    locked = useRef(false);
  const pending = useRef<{
    signature: string;
    request: ProcessingCreateRequest;
    dispatched?: boolean;
  } | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [submittedJobId, setSubmittedJobId] = useState<string | null>(null);
  const [observedJob, setObservedJob] = useState<{ id: string; state: JobState } | null>(null);
  const actions = useKnowledgeProcessingActions(scope, spaceId);
  const recentJobs = useKnowledgeProcessingJobs(
    scope,
    spaceId,
    { page: 1, page_size: 1, kind: "metadata_schema_change" },
    undefined,
    { refetchOnMount: "always", enabled },
  );
  const lookupComplete = recentJobs.isFetchedAfterMount;
  const latestJob = lookupComplete ? recentJobs.data?.data[0] : undefined;
  const jobId = submittedJobId ?? latestJob?.id;
  const jobState = observedJob && observedJob.id === jobId
    ? observedJob.state
    : submittedJobId ? "accepted" : latestJob?.state;
  const processing = jobState === "accepted" || jobState === "running";
  const schema = useQuery({
    queryKey: knowledgeQueryKeys.metadataSchema(scope, spaceId),
    queryFn: () => readMetadataSchema(spaceId),
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
  });
  const { data: schemaData, refetch } = schema;
  const canEdit = Boolean(schemaData) && lookupComplete && !processing;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (schema.error) showApiError(schema.error);
  }, [schema.error]);
  const change = useCallback(
    async (value: MetadataSchemaChange) => {
      if (!alive.current || locked.current || !canEdit || !schemaData)
        throw new Error(t("f118.processing_unavailable"));
      locked.current = true;
      try {
        const signature = JSON.stringify(value);
        if (pending.current?.dispatched && pending.current.signature !== signature)
          throw new Error(t("fileMetadata.uncertain"));
        if (pending.current?.signature !== signature) {
          const plan = await actions.precheck({
            kind: "metadata_schema_change",
            parameters: {
              expected_schema_revision: schemaData.revision,
              changes: [value],
            },
          });
          if (!alive.current)
            throw new DOMException("Retired metadata editor", "AbortError");
          if (
            !plan.can_execute ||
            !plan.check_complete ||
            plan.requires_skip_confirmation ||
            plan.invalid_items.length > 0
          )
            throw new Error(t("f118.processing_unavailable"));
          pending.current = {
            signature,
            request: {
              confirmation_id: plan.confirmation_id,
              plan_digest: plan.plan_digest,
              idempotency_key: createDshOperationId(),
            },
          };
        }
        pending.current.dispatched = true;
        const accepted = await actions.createJob(pending.current.request);
        if (alive.current) setUncertain(false);
        pending.current = null;
        if (!alive.current)
          throw new DOMException("Retired metadata editor", "AbortError");
        if ("job_id" in accepted) setSubmittedJobId(accepted.job_id);
      } catch (error) {
        if (
          isApiError(error) &&
          (error.kind === "business" ||
            (error.kind === "http" && (error.httpStatus ?? 0) < 500))
        )
          pending.current = null;
        if (alive.current) {
          setUncertain(Boolean(pending.current?.dispatched));
          showApiError(error);
        }
        throw error;
      } finally {
        locked.current = false;
      }
    },
    [actions, canEdit, schemaData, t],
  );
  const mutations = useMemo(
    () => ({
      add: (field_name: string, type: string) => {
        if (type !== "string" && type !== "number" && type !== "time")
          return Promise.reject(new Error(t("inputInvalid")));
        return change({ operation: "add", field_name, field_type: type });
      },
      rename: (field_name: string, new_field_name: string) =>
        change({ operation: "rename", field_name, new_field_name }),
      remove: (field_name: string) =>
        change({ operation: "delete", field_name }),
    }),
    [change, t],
  );
  const handleStateChange = useCallback((state: JobState) => {
    if (jobId) setObservedJob({ id: jobId, state });
  }, [jobId]);
  const handleCompleted = useCallback(() => {
    if (!alive.current) return;
    void refetch();
    toast.show({ type: "success", message: t("detail.saved") });
  }, [refetch, t]);
  return { uncertain, schema, recentJobs, canEdit, mutations, jobId, jobState, handleStateChange, handleCompleted, refetch };
}
