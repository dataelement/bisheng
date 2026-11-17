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
import { useQueryClient } from "@tanstack/react-query";
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
  const [plan, setPlan] = useState<{
    value: OperationPrecheck;
    key: string;
    destinationLabel: string;
  } | null>(null);
  const [destinationLabel, setDestinationLabel] = useState(
    t(parentId === null ? "move.current_space" : "move.current_folder"),
  );
  const [skip, setSkip] = useState(false),
    [busy, setBusy] = useState(false);
  const [dispatched, setDispatched] = useState(false),
    [completed, setCompleted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  closeGuard.current = () => !busy && (!dispatched || !!jobId || completed);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const tenant = scope.managementTenantId ?? scope.tenantId;
  const current = () =>
    alive.current &&
    (managementRequestScope() === null || managementRequestScope() === tenant);
  const refresh = () => {
    void client.invalidateQueries({
      queryKey: knowledgeQueryKeys.scope(scope),
    });
  };
  const handleReview = async () => {
    if (busy || dispatched || !current()) return;
    setBusy(true);
    try {
      const value = await precheckMove(spaceId, items, destination, tenant);
      if (current()) {
        setPlan({ value, key: createOperationId(), destinationLabel });
        setSkip(false);
      }
    } catch (error) {
      if (current()) showApiError(error);
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  const handleConfirm = async () => {
    if (
      busy ||
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
        setPlan(null);
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
          {!plan && (
            <fieldset className="min-w-0" disabled={busy}>
              <MoveDestinationPicker
                scope={scope}
                sourceId={spaceId}
                value={destination}
                onChange={(next, label) => {
                  setDestination(next);
                  setDestinationLabel(label);
                }}
              />
            </fieldset>
          )}
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
          (plan ? (
            <>
              {!dispatched && (
                <Button
                  variant="outlined"
                  disabled={busy}
                  onClick={() => setPlan(null)}
                >
                  {t("f118.processing_review_again")}
                </Button>
              )}
              <Button
                disabled={
                  busy ||
                  !plan.value.can_execute ||
                  !plan.value.check_complete ||
                  (plan.value.invalid_items.length > 0 && !skip)
                }
                onClick={() => {
                  void handleConfirm();
                }}
              >
                {t(dispatched ? "retry" : "confirm", {
                  ns: dispatched ? "knowledge" : "bs",
                })}
              </Button>
            </>
          ) : (
            <Button
              disabled={busy || !items.length}
              onClick={() => {
                void handleReview();
              }}
            >
              {t("f118.processing_review_action")}
            </Button>
          ))}
      </DialogFooter>
    </DialogContent>
  );
}
