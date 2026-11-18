import { KnowledgeDialogTable, MoveConfirmation, MoveToDialog } from "@bisheng/knowledge";
import { toast } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  confirmMove,
  precheckMove,
  type MoveDestination,
  type MoveSelection,
} from "@/controllers/API/knowledgeMove";
import { createMoveDestinationServices } from "@/controllers/API/knowledgeMoveDestinations";
import type { OperationPrecheck } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { managementRequestScope } from "@/controllers/managementScope";
import { showApiError } from "@/controllers/request";
import { createDshOperationId as createOperationId } from "@/util/dshOperationId";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";

interface MoveDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  items: readonly MoveSelection[];
  onClose: () => void;
}

/** Own one immutable review until success or an explicit stale-plan response. */
export function MoveDialog(props: MoveDialogProps) {
  return (
    <Content
      key={JSON.stringify([
        props.scope,
        props.spaceId,
        props.parentId,
        props.items,
      ])}
      {...props}
    />
  );
}

function Content({
  scope,
  spaceId,
  parentId,
  items,
  onClose,
}: MoveDialogProps) {
  const { t, i18n } = useTranslation("knowledge");
  const { t: moveText } = useTranslation("shared", {
    keyPrefix: "knowledge.move",
  });
  const client = useQueryClient();
  const [destination, setDestination] = useState<MoveDestination>({
    spaceId,
    folderId: parentId,
  });
  const [attempt, setAttempt] = useState(0);
  const [pickerOpen, setPickerOpen] = useState(true);
  const [destinationSelected, setDestinationSelected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dispatched, setDispatched] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const tenant = scope.managementTenantId ?? scope.tenantId;
  const services = useMemo(
    () => createMoveDestinationServices(tenant),
    [tenant],
  );
  // The shared picker closes before reporting its selected destination.
  useEffect(() => {
    if (!pickerOpen && !destinationSelected) onClose();
  }, [pickerOpen, destinationSelected, onClose]);
  const review = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.scope(scope),
      "move-review",
      spaceId,
      parentId,
      items,
      destination,
      attempt,
    ],
    queryFn: async (): Promise<{ value: OperationPrecheck; key: string }> => ({
      value: await precheckMove(spaceId, items, destination, tenant),
      key: createOperationId(),
    }),
    enabled:
      items.length > 0 && destinationSelected && !dispatched && !completed,
    staleTime: Infinity,
    cacheTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const plan = review.data;
  useEffect(() => {
    if (review.error) showApiError(review.error);
  }, [review.error]);
  const canClose = !busy && (!dispatched || !!jobId || completed);
  const writing = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const current = useCallback(
    () =>
      alive.current &&
      (managementRequestScope() === null ||
        managementRequestScope() === tenant),
    [tenant],
  );
  const refresh = useCallback(() => {
    void client.invalidateQueries({
      queryKey: knowledgeQueryKeys.scope(scope),
    });
  }, [client, scope]);
  const finish = useCallback(
    (count: number) => {
      if (!current()) return;
      setCompleted(true);
      refresh();
      toast.show({ type: "success", message: moveText("success", { count }) });
      onClose();
    },
    [current, refresh, moveText, onClose],
  );
  const handleConfirm = useCallback(async () => {
    if (
      writing.current ||
      review.isFetching ||
      review.isError ||
      !current() ||
      !plan?.value.can_execute ||
      !plan.value.check_complete
    )
      return;
    writing.current = true;
    setBusy(true);
    setDispatched(true);
    try {
      const result = await confirmMove(
        spaceId,
        {
          confirmation_id: plan.value.confirmation_id,
          plan_digest: plan.value.plan_digest,
          idempotency_key: plan.key,
        },
        tenant,
      );
      if (!current()) return;
      if ("job_id" in result) {
        setJobId(result.job_id);
        refresh();
      } else finish(result.moved.length);
    } catch (error) {
      if (!current()) return;
      showApiError(error);
      const code =
        error && typeof error === "object" && "status_code" in error
          ? error.status_code
          : undefined;
      if (code === 18087 || code === 18088) {
        setAttempt((value) => value + 1);
        setDispatched(false);
      }
    } finally {
      writing.current = false;
      if (alive.current) setBusy(false);
    }
  }, [
    review.isFetching,
    review.isError,
    current,
    plan,
    spaceId,
    tenant,
    refresh,
    finish,
  ]);
  const automaticAttempt = useRef<string | null>(null);
  useEffect(() => {
    if (
      !plan ||
      dispatched ||
      completed ||
      review.isFetching ||
      review.isError ||
      destination.spaceId !== spaceId ||
      plan.value.impact.cross_space === true ||
      plan.value.invalid_items.length > 0 ||
      !plan.value.can_execute ||
      !plan.value.check_complete ||
      automaticAttempt.current === plan.key
    )
      return;
    automaticAttempt.current = plan.key;
    void handleConfirm();
  }, [
    plan,
    dispatched,
    completed,
    destination.spaceId,
    spaceId,
    review.isFetching,
    review.isError,
    handleConfirm,
  ]);
  if (pickerOpen)
    return (
      <MoveToDialog
        open
        onOpenChange={setPickerOpen}
        currentSpaceId={String(spaceId)}
        services={services}
        onError={showApiError}
        onConfirm={(targetSpaceId, targetFolderId) => {
          setDestination({
            spaceId: Number(targetSpaceId),
            folderId: targetFolderId === null ? null : Number(targetFolderId),
          });
          setDestinationSelected(true);
        }}
      />
    );
  if (!destinationSelected || completed) return null;
  const invalidGroups = new Map<string, string[]>();
  for (const item of plan?.value.invalid_items ?? []) {
    const reason = i18n.exists(`knowledge:batch.reason_${item.reason}`)
      ? t(`batch.reason_${item.reason}`)
      : t("f118.processing_unavailable");
    const names = invalidGroups.get(reason) ?? [];
    names.push(item.name ?? t("f118.processing_unavailable"));
    invalidGroups.set(reason, names);
  }
  const removedFields = plan?.value.impact.removed_fields;
  const crossSpaceImpact =
    plan &&
    (destination.spaceId !== spaceId || plan.value.impact.cross_space === true)
      ? moveText("review_impact", {
          count:
            typeof plan.value.impact.logical_count === "number"
              ? plan.value.impact.logical_count
              : plan.value.valid_items.length,
          fields:
            Array.isArray(removedFields) && removedFields.length
              ? removedFields.join(", ")
              : moveText("no_removed_fields"),
        })
      : null;
  return (
    <MoveConfirmation
      open
      title={moveText("review_title")}
      busy={busy || review.isFetching}
      canCancel={canClose}
      hideCancel={dispatched}
      cancelText={moveText("cancel_all")}
      confirmText={
        jobId
          ? moveText("close")
          : dispatched || review.isError
            ? moveText("retry")
            : moveText("move_here")
      }
      canConfirm={
        !!jobId ||
        review.isError ||
        !!(plan?.value.can_execute && plan.value.check_complete)
      }
      onCancel={() => {
        if (canClose) onClose();
      }}
      onConfirm={() => {
        if (jobId) onClose();
        else if (review.isError) void review.refetch();
        else void handleConfirm();
      }}
      description={
        jobId ? (
          <SpaceProcessingProgress
            scope={scope}
            spaceId={spaceId}
            jobId={jobId}
            kind="move_index"
            onCompleted={() => finish(plan?.value.valid_items.length ?? 0)}
          />
        ) : review.isFetching ? (
          moveText("loading")
        ) : review.isError ? (
          moveText("load_failed")
        ) : (
          <div className="space-y-3">
            {invalidGroups.size > 0 && (
              <KnowledgeDialogTable
                caption={t("batch.invalid")}
                columns={[{ label: t("batch.column_name") }, { label: t("batch.column_reason") }]}
                rows={[...invalidGroups].flatMap(([reason, names]) =>
                  names.map((name, index) => ({
                    key: `${reason}-${index}`,
                    cells: [name, reason],
                  })),
                )}
              />
            )}
            {crossSpaceImpact && <p>{crossSpaceImpact}</p>}
            {dispatched && !busy && <p>{t("move.unknown_ack")}</p>}
          </div>
        )
      }
    />
  );
}
