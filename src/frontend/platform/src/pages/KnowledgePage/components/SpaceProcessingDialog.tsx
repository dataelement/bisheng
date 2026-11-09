import { Button, Input, Pagination, Select } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { getModelListApi } from "@/controllers/API/finetune";
import type {
  OperationPrecheck,
  ProcessingPrecheckRequest,
  ProcessingTargetInput,
} from "@/controllers/API/knowledgeSpace";
import {
  precheckSpaceCopy,
  confirmSpaceCopy,
  readProcessingTarget,
  readMetadataSchema,
} from "@/controllers/API/knowledgeProcessing";
import {
  useKnowledgeProcessingActions,
  useKnowledgeProcessingJobs,
  useKnowledgeProcessingSettings,
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { showApiError } from "@/controllers/request";
import { ModelSelect } from "../../ModelPage/manage/tabs/WorkbenchModel";
import { embeddingGroups } from "./KnowledgeLibraryDialog";
import {
  ProcessingDefaultsEditor,
  processingDefaultsToDraft,
  validateProcessingDefaultsDraft,
  type ProcessingDefaultsDraft,
} from "./ProcessingDefaultsEditor";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";

interface SpaceProcessingDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  mode: "copy" | "embedding" | "file" | "jobs" | "schema";
  target?: ProcessingTargetInput;
  fileId?: number;
  includeCopies?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
}
export function SpaceProcessingDialog(props: SpaceProcessingDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {props.open && (
        <Content
          key={JSON.stringify([
            props.scope,
            props.spaceId,
            props.target,
            props.fileId,
            props.mode,
          ])}
          {...props}
        />
      )}
    </Dialog>
  );
}
function Content({
  scope,
  spaceId,
  mode,
  target,
  fileId,
  includeCopies = false,
  onOpenChange,
  onSaved,
}: SpaceProcessingDialogProps) {
  const { t } = useTranslation("knowledge");
  const actions = useKnowledgeProcessingActions(scope, spaceId);
  const [jobsPage, setJobsPage] = useState(1);
  const paginationLocale = usePaginationLocale();
  const selectLabels = useSelectLabels();
  const [schemaOperation, setSchemaOperation] = useState<
    "add" | "rename" | "delete"
  >("add");
  const [fieldName, setFieldName] = useState(""),
    [newFieldName, setNewFieldName] = useState("");
  const [fieldType, setFieldType] = useState<"string" | "number" | "time">(
    "string",
  );
  const schema = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "metadata-schema"],
    queryFn: () => readMetadataSchema(spaceId),
    enabled: mode === "schema" && Boolean(scope.identityKey),
    cacheTime: 0,
  });
  const settings = useKnowledgeProcessingSettings(scope, spaceId);
  const models = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(scope), "embedding-candidates"],
    queryFn: async () => embeddingGroups(await getModelListApi()),
    enabled: mode === "embedding" && Boolean(scope.identityKey),
  });
  const jobs = useKnowledgeProcessingJobs(scope, spaceId, {
    page: jobsPage,
    page_size: 20,
  });
  const copies = useKnowledgeProcessingJobs(
    includeCopies && mode === "jobs" ? scope : { ...scope, identityKey: "" },
    spaceId,
    { page: jobsPage, page_size: 20, kind: "space_copy" },
  );
  const [name, setName] = useState(""),
    [model, setModel] = useState("");
  const [kind, setKind] = useState<"file_reprocess" | "file_resplit">(
    "file_reprocess",
  );
  const [draft, setDraft] = useState<ProcessingDefaultsDraft | null>(null);
  const [plan, setPlan] = useState<{
    result: OperationPrecheck;
    key: string;
  } | null>(null);
  const [job, setJob] = useState<{
    id: string;
    space: number;
    kind?: "space_copy";
  } | null>(null);
  const [busy, setBusy] = useState(false),
    [completed, setCompleted] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (settings.data)
      setDraft(processingDefaultsToDraft(settings.data.effective_defaults));
  }, [settings.data]);
  useEffect(() => {
    const error =
      settings.error ||
      models.error ||
      jobs.error ||
      copies.error ||
      schema.error;
    if (error) showApiError(error);
  }, [settings.error, models.error, jobs.error, copies.error, schema.error]);
  const validation = draft ? validateProcessingDefaultsDraft(draft) : null;
  const handleReview = async () => {
    if (busy) return;
    setBusy(true);
    try {
      let result: OperationPrecheck;
      if (mode === "copy") result = await precheckSpaceCopy(spaceId, name);
      else {
        let request: ProcessingPrecheckRequest;
        if (mode === "embedding")
          request = {
            kind: "embedding_rebuild",
            parameters: { embedding_model_id: model ? Number(model) : null },
          };
        else if (mode === "schema") {
          if (!schema.data || !fieldName.trim()) return;
          const change =
            schemaOperation === "add"
              ? {
                  operation: "add" as const,
                  field_name: fieldName,
                  field_type: fieldType,
                }
              : schemaOperation === "rename"
                ? {
                    operation: "rename" as const,
                    field_name: fieldName,
                    new_field_name: newFieldName,
                  }
                : { operation: "delete" as const, field_name: fieldName };
          request = {
            kind: "metadata_schema_change",
            parameters: {
              expected_schema_revision: schema.data.revision,
              changes: [change],
            },
          };
        } else {
          if (!validation?.ok) return;
          const actualTarget =
            target ??
            (fileId ? await readProcessingTarget(spaceId, fileId) : null);
          if (!alive.current || !actualTarget) return;
          request = {
            kind,
            targets: [actualTarget],
            parameters: {
              overrides: {
                document: validation.value.document,
                table: validation.value.table,
              },
            },
          };
        }
        result = await actions.precheck(request);
      }
      if (alive.current) setPlan({ result, key: crypto.randomUUID() });
    } catch (error) {
      if (alive.current) showApiError(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const handleConfirm = async () => {
    if (
      !plan ||
      busy ||
      !plan.result.can_execute ||
      !plan.result.check_complete
    )
      return;
    setBusy(true);
    const request = {
      confirmation_id: plan.result.confirmation_id,
      plan_digest: plan.result.plan_digest,
      idempotency_key: plan.key,
    };
    try {
      if (mode === "copy") {
        const result = await confirmSpaceCopy(spaceId, request);
        if (!alive.current) return;
        if (result.processing_job)
          setJob({
            id: result.processing_job.job_id,
            space: result.knowledge.id,
            kind: "space_copy",
          });
        else setCompleted(result.completed);
      } else {
        const result = await actions.createJob(request);
        if (!alive.current) return;
        if ("completed" in result) setCompleted(result.completed);
        else setJob({ id: result.job_id, space: spaceId });
      }
      onSaved?.();
    } catch (error) {
      if (alive.current) showApiError(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  return (
    <DialogContent
      className="max-h-[85vh] max-w-3xl overflow-y-auto"
      aria-describedby={undefined}
    >
      <DialogHeader>
        <DialogTitle>{t(`f118.processing_title_${mode}`)}</DialogTitle>
      </DialogHeader>
      {!job && !completed && mode !== "jobs" && (
        <p>
          {t(
            mode === "file"
              ? "f118.processing_overwrite_warning"
              : mode === "copy"
                ? "f118.processing_copy_notice"
                : mode === "schema"
                  ? "f118.processing_schema_notice"
                  : "f118.processing_rebuild_notice",
          )}
        </p>
      )}
      {job ? (
        <SpaceProcessingProgress
          scope={scope}
          spaceId={job.space}
          jobId={job.id}
          kind={job.kind}
          onCompleted={onSaved}
        />
      ) : completed ? (
        <p>{t("completed")}</p>
      ) : mode === "jobs" ? (
        <ul>
          {[...(jobs.data?.data ?? []), ...(copies.data?.data ?? [])].map(
            (row) => (
              <li key={row.id}>
                <Button
                  variant="link"
                  onClick={() =>
                    setJob({
                      id: row.id,
                      space: spaceId,
                      ...(row.kind === "space_copy"
                        ? { kind: "space_copy" as const }
                        : {}),
                    })
                  }
                >
                  {t(`f118.processing_kind_${row.kind}`)} ·{" "}
                  {t(`f118.processing_state_${row.state}`)}
                </Button>
              </li>
            ),
          )}
        </ul>
      ) : (
        <>
          <fieldset disabled={busy || Boolean(plan)} className="space-y-4">
            {mode === "copy" && (
              <Input
                aria-label={t("f118.space_name")}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            )}
            {mode === "embedding" && (
              <ModelSelect
                label={t("f118.embedding_model")}
                value={model}
                close
                options={models.data ?? []}
                onChange={(value: string) => setModel(value)}
              />
            )}
            {mode === "schema" && (
              <section className="space-y-3">
                <Select
                  {...selectLabels}
                  value={schemaOperation}
                  options={["add", "rename", "delete"].map((value) => ({
                    value,
                    label: t(`f118.processing_schema_${value}`),
                  }))}
                  onChange={(value) => {
                    setSchemaOperation(value as typeof schemaOperation);
                    setFieldName("");
                  }}
                />
                {schemaOperation === "add" ? (
                  <Input
                    aria-label={t("f118.processing_field_name")}
                    value={fieldName}
                    onChange={(event) => setFieldName(event.target.value)}
                  />
                ) : (
                  <Select
                    {...selectLabels}
                    value={fieldName || undefined}
                    options={(schema.data?.fields ?? [])
                      .filter((row) => row.field_name?.trim())
                      .map((row) => ({
                        value: row.field_name,
                        label: row.field_name,
                      }))}
                    onChange={(value) => setFieldName(String(value))}
                  />
                )}
                {schemaOperation === "rename" && (
                  <Input
                    aria-label={t("f118.processing_field_name")}
                    value={newFieldName}
                    onChange={(event) => setNewFieldName(event.target.value)}
                  />
                )}
                {schemaOperation === "add" && (
                  <Select
                    {...selectLabels}
                    value={fieldType}
                    options={["string", "number", "time"].map((value) => ({
                      value,
                      label: t(`f118.processing_field_${value}`),
                    }))}
                    onChange={(value) =>
                      setFieldType(value as typeof fieldType)
                    }
                  />
                )}
              </section>
            )}
            {mode === "file" && (
              <>
                <div className="flex gap-2">
                  <Button
                    variant={kind === "file_reprocess" ? "solid" : "outlined"}
                    onClick={() => setKind("file_reprocess")}
                  >
                    {t("f118.processing_kind_file_reprocess")}
                  </Button>
                  <Button
                    variant={kind === "file_resplit" ? "solid" : "outlined"}
                    onClick={() => setKind("file_resplit")}
                  >
                    {t("f118.processing_kind_file_resplit")}
                  </Button>
                </div>
                {draft && (
                  <ProcessingDefaultsEditor value={draft} onChange={setDraft} />
                )}
              </>
            )}
          </fieldset>
          {plan && (
            <section>
              <p>
                {t("f118.processing_review", {
                  valid: plan.result.valid_items.length,
                  invalid: plan.result.invalid_items.length,
                })}
              </p>
              {plan.result.invalid_items.map((item, index) => (
                <p key={index}>
                  {item.name ?? t("f118.processing_unavailable")}: {item.reason}
                </p>
              ))}
            </section>
          )}
        </>
      )}
      {mode === "jobs" &&
        !job &&
        Math.max(jobs.data?.total ?? 0, copies.data?.total ?? 0) > 20 && (
          <Pagination
            current={jobsPage}
            total={Math.max(jobs.data?.total ?? 0, copies.data?.total ?? 0)}
            pageSize={20}
            onChange={setJobsPage}
            locale={paginationLocale}
          />
        )}
      <DialogFooter>
        <Button
          variant="outlined"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          {t("close", { ns: "bs" })}
        </Button>
        {!job &&
          !completed &&
          mode !== "jobs" &&
          (plan ? (
            <>
              <Button
                variant="outlined"
                disabled={busy}
                onClick={() => setPlan(null)}
              >
                {t("f118.processing_review_again")}
              </Button>
              <Button
                disabled={
                  busy ||
                  !plan.result.can_execute ||
                  !plan.result.check_complete
                }
                onClick={() => void handleConfirm()}
              >
                {t("confirm", { ns: "bs" })}
              </Button>
            </>
          ) : (
            <Button
              disabled={
                busy ||
                (mode === "copy" && !name.trim()) ||
                (mode === "file" && !validation?.ok) ||
                (mode === "schema" &&
                  (!schema.data ||
                    !fieldName.trim() ||
                    (schemaOperation === "rename" && !newFieldName.trim())))
              }
              onClick={() => void handleReview()}
            >
              {t("f118.processing_review_action")}
            </Button>
          ))}
      </DialogFooter>
    </DialogContent>
  );
}
