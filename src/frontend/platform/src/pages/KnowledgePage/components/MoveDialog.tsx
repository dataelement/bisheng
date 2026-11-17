import { Button, Checkbox } from "@bisheng/ui";
import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import {
  confirmMove,
  precheckMove,
  type MoveDestination,
  type MoveSelection,
} from "@/controllers/API/knowledgeMove";
import type { OperationPrecheck } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { managementRequestScope } from "@/controllers/managementScope";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { showApiError } from "@/controllers/request";
import { createDshOperationId as createOperationId } from "@/util/dshOperationId";
import { MoveDestinationPicker } from "./MoveDestinationPicker";
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
  const closeGuard = useRef(() => true);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && closeGuard.current()) props.onClose();
      }}
    >
      <Content
        key={JSON.stringify([
          props.scope,
          props.spaceId,
          props.parentId,
          props.items,
        ])}
        {...props}
        closeGuard={closeGuard}
      />
    </Dialog>
  );
}
function Content({
  scope,
  spaceId,
  parentId,
  items,
  onClose,
  closeGuard,
}: MoveDialogProps & { closeGuard: MutableRefObject<() => boolean> }) {
  const { t, i18n } = useTranslation("knowledge");
  const client = useQueryClient();
  const [destination, setDestination] = useState<MoveDestination>({
    spaceId,
    folderId: parentId,
  });
  const [attempt, setAttempt] = useState(0);
  const [destinationSelected, setDestinationSelected] = useState(false);
  const [destinationLabel, setDestinationLabel] = useState(
    t(parentId === null ? "move.current_space" : "move.current_folder"),
  );
  const [skip, setSkip] = useState(false),
    [busy, setBusy] = useState(false);
  const [dispatched, setDispatched] = useState(false),
    [completed, setCompleted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const tenant = scope.managementTenantId ?? scope.tenantId;
  const review = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(scope), "move-review", spaceId, parentId, items, destination, attempt],
    queryFn: async (): Promise<{ value: OperationPrecheck; key: string; destinationLabel: string }> => ({
      value: await precheckMove(spaceId, items, destination, tenant),
      key: createOperationId(),
      destinationLabel,
    }),
    enabled: items.length > 0 && destinationSelected && !dispatched && !completed,
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
  closeGuard.current = () => !busy && (!dispatched || !!jobId || completed);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const current = () =>
    alive.current &&
    (managementRequestScope() === null || managementRequestScope() === tenant);
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: knowledgeQueryKeys.scope(scope),
    });
  };
  const handleConfirm = async () => {
    if (
      busy ||
      review.isFetching ||
      review.isError ||
      !current() ||
      !plan?.value.can_execute ||
      !plan.value.check_complete ||
      (plan.value.invalid_items.length > 0 && !skip)
    )
      return;
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
      if ("job_id" in result) setJobId(result.job_id);
      else setCompleted(true);
      refresh();
    } catch (error) {
      if (!current()) return;
      showApiError(error);
      const code =
        error && typeof error === "object" && "status_code" in error
          ? error.status_code
          : undefined;
      if (code === 18087 || code === 18088) {
        setAttempt((value) => value + 1);
        setSkip(false);
        setDispatched(false);
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const names = (key: string) => {
    const value = plan?.value.impact[key];
    return Array.isArray(value)
      ? value
          .filter((item): item is string => typeof item === "string")
          .join(", ")
      : "";
  };
  return (
    <DialogContent
      aria-describedby={undefined}
      className={`max-h-[85vh] overflow-y-auto ${!plan && !jobId && !completed ? "w-[calc(100vw-32px)] max-w-3xl" : ""}`}
    >
      <DialogHeader>
        <DialogTitle>
          {t("move.title")}
        </DialogTitle>
      </DialogHeader>
      {jobId ? (
        <SpaceProcessingProgress
          scope={scope}
          spaceId={spaceId}
          jobId={jobId}
          kind="move_index"
          onCompleted={refresh}
        />
      ) : completed ? (
        <p role="status">{t("move.completed")}</p>
      ) : (
        <>
            <fieldset className="min-w-0" disabled={busy || dispatched}>
              <MoveDestinationPicker
                scope={scope}
                sourceId={spaceId}
                value={destination}
                onChange={(next, label) => {
                  setDestination(next);
                  setDestinationLabel(label);
                  setDestinationSelected(true);
                  setSkip(false);
                }}
              />
            </fieldset>
          {review.isFetching && <p role="status">{t("move.checking")}</p>}
          {plan && (
            <section className="space-y-3">
              <p>
                {t("move.destination", { destination: plan.destinationLabel })}
              </p>
              <p>
                {t("move.review", { count: plan.value.valid_items.length })}
              </p>
              <p>{t("move.whole_versions")}</p>
              {plan.value.impact.cross_space === true && (
                <>
                  <p>{t("move.permissions")}</p>
                  <p>{t("move.tags")}</p>
                  <p>
                    {t("move.retained_fields", {
                      fields: names("retained_fields") || t("move.none"),
                    })}
                  </p>
                  <p>
                    {t("move.removed_fields", {
                      fields: names("removed_fields") || t("move.none"),
                    })}
                  </p>
                  <p>{t("move.async_notice")}</p>
                </>
              )}
              <ul>
                {plan.value.invalid_items.map((item, index) => (
                  <li key={index}>
                    {item.name ?? t("f118.processing_unavailable")}:{" "}
                    {i18n.exists(`knowledge:batch.reason_${item.reason}`)
                      ? t(`batch.reason_${item.reason}`)
                      : t("f118.processing_unavailable")}
                  </li>
                ))}
              </ul>
              {plan.value.invalid_items.length > 0 && (
                <Checkbox
                  checked={skip}
                  label={t("move.skip_invalid")}
                  onCheckedChange={(checked) => setSkip(checked === true)}
                />
              )}
              {dispatched && <p role="status">{t("move.unknown_ack")}</p>}
            </section>
          )}
        </>
      )}
      <DialogFooter>
        <Button
          variant="outlined"
          disabled={!closeGuard.current()}
          onClick={onClose}
        >
          {t("close", { ns: "bs" })}
        </Button>
        {!jobId &&
          !completed &&
          (
              <Button
                disabled={
                  busy ||
                  review.isFetching ||
                  (!review.isError && (!plan?.value.can_execute ||
                  !plan.value.check_complete ||
                  (plan.value.invalid_items.length > 0 && !skip)))
                }
                onClick={() => {
                  if (review.isError) void review.refetch();
                  else void handleConfirm();
                }}
              >
                {t(dispatched || review.isError ? "retry" : "confirm", {
                  ns: dispatched || review.isError ? "knowledge" : "bs",
                })}
              </Button>
          )}
      </DialogFooter>
    </DialogContent>
  );
}
