import { Button, Pagination } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog } from "@/components/bs-ui/dialog";
import { getModelListApi } from "@/controllers/API/finetune";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceInfo,
  type ProcessingKind,
  type OperationPrecheck,
  type ProcessingPrecheckRequest,
  type ProcessingTargetInput,
} from "@/controllers/API/knowledgeSpace";
import {
  readProcessingTarget,
} from "@/controllers/API/knowledgeProcessing";
import {
  useKnowledgeProcessingActions,
  useKnowledgeProcessingJobs,
  useKnowledgeProcessingSettings,
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { createDshOperationId as createOperationId } from "@/util/dshOperationId";
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
import { SpacePanelFrame } from "./SpacePanelFrame";
import { SpaceProcessingActions } from "./SpaceProcessingActions";

interface SpaceProcessingDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  mode: "embedding" | "file" | "jobs";
  target?: ProcessingTargetInput;
  fileId?: number;
  includeCopies?: boolean;
  jobKind?: ProcessingKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: () => void;
  presentation?: "page";
}
export function SpaceProcessingDialog(props: SpaceProcessingDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      {props.open && (
        <Content
          key={JSON.stringify([props.scope, props.spaceId, props.target, props.fileId, props.mode])}
          {...props}
        />
      )}
    </Dialog>
  );
}
export function SpaceProcessingPanel(
  props: Omit<SpaceProcessingDialogProps, "open" | "onOpenChange" | "presentation">,
) {
  return (
    <Content
      key={JSON.stringify([props.scope, props.spaceId, props.mode])}
      {...props}
      open
      presentation="page"
      onOpenChange={() => undefined}
    />
  );
}

function Content({
  scope,
  spaceId,
  mode,
  target,
  fileId,
  includeCopies = false,
  jobKind,
  onOpenChange,
  onSaved,
  presentation,
}: SpaceProcessingDialogProps) {
  const { t, i18n } = useTranslation("knowledge");
  const invalidReason = (reason: string) =>
    i18n.exists(`knowledge:batch.reason_${reason}`)
      ? t(`batch.reason_${reason}`)
      : t("f118.processing_unavailable");
  const actions = useKnowledgeProcessingActions(scope, spaceId);
  const instance = useId();
  const configured = useQuery<KnowledgeSpaceInfo>({
    queryKey: [...knowledgeQueryKeys.info(scope, spaceId), "processing-opening", instance],
    queryFn: () => knowledgeSpaceApi.getSpaceInfo(spaceId),
    enabled: mode === "embedding" && Boolean(scope.identityKey),
    cacheTime: 0,
    retry: false,
  });
  const [jobsPage, setJobsPage] = useState(1);
  const paginationLocale = usePaginationLocale();
  const settings = useKnowledgeProcessingSettings(
    mode === "file" ? scope : { ...scope, identityKey: "" },
    spaceId,
  );
  const models = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(scope), "embedding-candidates"],
    queryFn: async () => embeddingGroups(await getModelListApi()),
    enabled: mode === "embedding" && Boolean(scope.identityKey),
  });
  const jobs = useKnowledgeProcessingJobs(
    mode === "jobs" ? scope : { ...scope, identityKey: "" },
    spaceId,
    {
      page: jobsPage,
      page_size: 20,
      ...(jobKind ? { kind: jobKind } : {}),
    },
  );
  const copies = useKnowledgeProcessingJobs(
    includeCopies && mode === "jobs" ? scope : { ...scope, identityKey: "" },
    spaceId,
    { page: jobsPage, page_size: 20, kind: "space_copy" },
  );
  const [model, setModel] = useState("");
  const modelInitialized = useRef(false);
  useEffect(() => {
    if (!modelInitialized.current && configured.data) {
      modelInitialized.current = true;
      setModel(String(configured.data.model ?? ""));
    }
  }, [configured.data]);
  const [kind, setKind] = useState<"file_reprocess" | "file_resplit">("file_reprocess");
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
    if (settings.data) setDraft(processingDefaultsToDraft(settings.data.effective_defaults));
  }, [settings.data]);
  useEffect(() => {
    const error =
      settings.error ||
      models.error ||
      jobs.error ||
      copies.error ||
      configured.error;
    if (error) showApiError(error);
  }, [settings.error, models.error, jobs.error, copies.error, configured.error]);
  const validation = draft ? validateProcessingDefaultsDraft(draft) : null;
  const handleReview = async () => {
    if (busy || (mode === "embedding" && !configured.isSuccess)) return;
    setBusy(true);
    try {
      let result: OperationPrecheck;
      {
        let request: ProcessingPrecheckRequest;
        if (mode === "embedding")
          request = {
            kind: "embedding_rebuild",
            parameters: {
              embedding_model_id:
                /^[1-9]\d*$/.test(model) && Number.isSafeInteger(Number(model))
                  ? Number(model)
                  : null,
            },
          };
        else {
          if (!validation?.ok) return;
          const actualTarget =
            target ?? (fileId ? await readProcessingTarget(spaceId, fileId) : null);
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
      if (alive.current) setPlan({ result, key: createOperationId() });
    } catch (error) {
      if (alive.current) showApiError(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const handleConfirm = async () => {
    if (!plan || busy || !plan.result.can_execute || !plan.result.check_complete) return;
    setBusy(true);
    const request = {
      confirmation_id: plan.result.confirmation_id,
      plan_digest: plan.result.plan_digest,
      idempotency_key: plan.key,
    };
    try {
      const result = await actions.createJob(request);
      if (!alive.current) return;
      if ("completed" in result) setCompleted(result.completed);
      else setJob({ id: result.job_id, space: spaceId });
      onSaved?.();
    } catch (error) {
      if (alive.current) showApiError(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  return (
    <SpacePanelFrame
      title={t(`f118.processing_title_${mode}`)}
      presentation={presentation}
      busy={busy}
      className="max-h-[85vh] max-w-3xl overflow-y-auto"
      footer={
        <SpaceProcessingActions
          busy={busy}
          showReview={!job && !completed && mode !== "jobs"}
          reviewDisabled={
            busy ||
            (mode === "embedding" && !configured.isSuccess) ||
            (mode === "file" && !validation?.ok)
          }
          hasPlan={Boolean(plan)}
          canExecute={Boolean(plan?.result.can_execute && plan.result.check_complete)}
          onClose={presentation !== "page" ? () => onOpenChange(false) : undefined}
          onReview={() => {
            void handleReview();
          }}
          onConfirm={() => {
            void handleConfirm();
          }}
          onReviewAgain={() => setPlan(null)}
        />
      }
    >
      {!job && !completed && mode !== "jobs" && (
        <p>
          {t(
            mode === "file"
              ? "f118.processing_overwrite_warning"
              : "f118.processing_rebuild_notice",
          )}
        </p>
      )}
      {job ? (
        <>
          {mode === "jobs" && (
            <Button variant="text" onClick={() => setJob(null)}>
              {t("detail.back_to_jobs")}
            </Button>
          )}
          <SpaceProcessingProgress
            scope={scope}
            spaceId={job.space}
            jobId={job.id}
            kind={job.kind}
            onCompleted={onSaved}
          />
        </>
      ) : completed ? (
        <p>{t("completed")}</p>
      ) : mode === "jobs" ? (
        <>
          {jobs.isInitialLoading && <p role="status">{t("f118.loading_space")}</p>}
          {jobs.isError && (
            <Button
              onClick={() => {
                void jobs.refetch();
              }}
            >
              {t("retry")}
            </Button>
          )}
          {!jobs.isInitialLoading && !jobs.isError && !jobs.data?.total && !copies.data?.total && (
            <p>{t("detail.no_jobs")}</p>
          )}
          <ul>
            {[...(jobs.data?.data ?? []), ...(copies.data?.data ?? [])].map((row) => (
              <li key={row.id}>
                <Button
                  variant="link"
                  onClick={() =>
                    setJob({
                      id: row.id,
                      space: spaceId,
                      ...(row.kind === "space_copy" ? { kind: "space_copy" as const } : {}),
                    })
                  }
                >
                  {t(`f118.processing_kind_${row.kind}`)} ·{" "}
                  {t(`f118.processing_state_${row.state}`)}
                </Button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <fieldset disabled={busy || Boolean(plan)} className="space-y-4">
            {mode === "embedding" && (
              <>
                <ModelSelect
                  label={t("f118.embedding_model")}
                  value={model}
                  close
                  options={models.data ?? []}
                  onChange={(value: string) => {
                    modelInitialized.current = true;
                    setModel(value);
                  }}
                />
                {configured.isInitialLoading && <p role="status">{t("f118.loading_space")}</p>}
                {configured.isError && (
                  <div role="alert">
                    <p>{t("f118.load_failed")}</p>
                    <Button
                      onClick={() => {
                        void configured.refetch();
                      }}
                    >
                      {t("retry")}
                    </Button>
                  </div>
                )}
              </>
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
                {draft && <ProcessingDefaultsEditor value={draft} onChange={setDraft} />}
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
                  {item.name ?? t("f118.processing_unavailable")}: {invalidReason(item.reason)}
                </p>
              ))}
            </section>
          )}
        </>
      )}
      {mode === "jobs" && !job && Math.max(jobs.data?.total ?? 0, copies.data?.total ?? 0) > 20 && (
        <Pagination
          current={jobsPage}
          total={Math.max(jobs.data?.total ?? 0, copies.data?.total ?? 0)}
          pageSize={20}
          onChange={setJobsPage}
          locale={paginationLocale}
        />
      )}
    </SpacePanelFrame>
  );
}
