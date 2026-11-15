import { Button, toast } from "@bisheng/ui";
import { isApiError } from "@bisheng/api-client";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  MetadataSchemaChange,
  ProcessingCreateRequest,
} from "@/controllers/API/knowledgeSpace";
import { readMetadataSchema } from "@/controllers/API/knowledgeProcessing";
import {
  knowledgeQueryKeys,
  useKnowledgeProcessingActions,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { createDshOperationId } from "@/util/dshOperationId";
import { showApiError } from "@/controllers/request";
import { MetadataManagementDialog } from "./MetadataManagementDialog";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";
interface SpaceMetadataPanelProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  onSaved?: () => void;
}
export function SpaceMetadataPanel(props: SpaceMetadataPanelProps) {
  return (
    <MetadataPanel
      key={JSON.stringify([props.scope, props.spaceId])}
      {...props}
    />
  );
}
function MetadataPanel({ scope, spaceId, onSaved }: SpaceMetadataPanelProps) {
  const { t } = useTranslation("knowledge");
  const alive = useRef(true),
    locked = useRef(false);
  const pending = useRef<{
    signature: string;
    request: ProcessingCreateRequest;
  } | null>(null);
  const [job, setJob] = useState<string | null>(null);
  const actions = useKnowledgeProcessingActions(scope, spaceId);
  const schema = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "metadata-schema"],
    queryFn: () => readMetadataSchema(spaceId),
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
  });
  const { data: schemaData, refetch } = schema;
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
      if (!alive.current || locked.current || job || !schemaData)
        throw new Error(t("f118.processing_unavailable"));
      locked.current = true;
      try {
        const signature = JSON.stringify(value);
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
        const accepted = await actions.createJob(pending.current.request);
        pending.current = null;
        if (!alive.current)
          throw new DOMException("Retired metadata editor", "AbortError");
        if ("job_id" in accepted) setJob(accepted.job_id);
        await refetch();
        if (alive.current) onSaved?.();
      } catch (error) {
        if (
          isApiError(error) &&
          (error.kind === "business" ||
            (error.kind === "http" && (error.httpStatus ?? 0) < 500))
        )
          pending.current = null;
        if (alive.current) showApiError(error);
        throw error;
      } finally {
        locked.current = false;
      }
    },
    [actions, job, schemaData, refetch, onSaved, t],
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
  const handleCompleted = useCallback(() => {
    if (!alive.current) return;
    setJob(null);
    void refetch();
    onSaved?.();
    toast.show({ type: "success", message: t("detail.saved") });
  }, [refetch, onSaved, t]);
  if (!schema.data)
    return (
      <div role={schema.isError ? "alert" : "status"}>
        <p>{t(schema.isError ? "f118.load_failed" : "f118.loading_space")}</p>
        {schema.isError && (
          <Button
            onClick={() => {
              void refetch();
            }}
          >
            {t("retry")}
          </Button>
        )}
      </div>
    );
  return (
    <div className="space-y-6">
      <MetadataManagementDialog
        open
        id={String(spaceId)}
        onOpenChange={() => undefined}
        presentation="page"
        initialMetadata={schema.data.fields}
        hasManagePermission={!job}
        mutations={mutations}
      />
      {job && (
        <SpaceProcessingProgress
          scope={scope}
          spaceId={spaceId}
          jobId={job}
          onCompleted={handleCompleted}
        />
      )}
    </div>
  );
}
