import { Button, Input } from "@bisheng/ui";
import { isApiError } from "@bisheng/api-client";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog } from "@/components/bs-ui/dialog";
import {
  precheckSpaceCopy,
  confirmSpaceCopy,
  type ProcessingCreateRequest,
  type SpaceCopyResult,
} from "@/controllers/API/knowledgeProcessing";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { createDshOperationId } from "@/util/dshOperationId";
import { SpacePanelFrame } from "./SpacePanelFrame";
import { SpaceProcessingProgress } from "./SpaceProcessingProgress";

interface SpaceCopyDialogProps {
  scope: KnowledgeQueryScope;
  source: KnowledgeSpaceInfo;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}
export function SpaceCopyDialog({
  scope,
  source,
  onClose,
  onCreated,
}: SpaceCopyDialogProps) {
  const { t } = useTranslation("knowledge");
  const suffix = t("copySuffix");
  const [name, setName] = useState(
    () => source.name.slice(0, Math.max(0, 200 - suffix.length)) + suffix,
  );
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SpaceCopyResult | null>(null);
  const [completed, setCompleted] = useState(false);
  const alive = useRef(true),
    locked = useRef(false);
  const pending = useRef<ProcessingCreateRequest | null>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const handleCreate = async () => {
    if (
      !alive.current ||
      locked.current ||
      result ||
      !name.trim() ||
      name.length > 200
    )
      return;
    locked.current = true;
    setBusy(true);
    try {
      if (!pending.current) {
        const plan = await precheckSpaceCopy(source.id, name.trim());
        if (!alive.current) return;
        if (
          !plan.check_complete ||
          !plan.can_execute ||
          plan.requires_skip_confirmation ||
          plan.invalid_items.length
        )
          throw new Error(t("f118.processing_unavailable"));
        pending.current = {
          confirmation_id: plan.confirmation_id,
          plan_digest: plan.plan_digest,
          idempotency_key: createDshOperationId(),
        };
      }
      const accepted = await confirmSpaceCopy(source.id, pending.current);
      if (!alive.current) return;
      pending.current = null;
      setResult(accepted);
      setCompleted(accepted.completed);
      await onCreated();
    } catch (error) {
      if (
        isApiError(error) &&
        (error.kind === "business" ||
          (error.kind === "http" && (error.httpStatus ?? 0) < 500))
      )
        pending.current = null;
      if (alive.current) showApiError(error);
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <SpacePanelFrame
        title={t("space_copy_ui.title")}
        busy={busy}
        footer={
          <>
            <Button
              color="default"
              variant="outlined"
              disabled={busy}
              onClick={onClose}
            >
              {t(result ? "close" : "cancel", {
                ns: result ? "bs" : "knowledge",
              })}
            </Button>
            {!result && (
              <Button
                loading={busy}
                disabled={busy || !name.trim() || name.length > 200}
                onClick={() => {
                  void handleCreate();
                }}
              >
                {t("space_copy_ui.create")}
              </Button>
            )}
          </>
        }
      >
        {!result ? (
          <div className="space-y-5 py-2 text-body">
            <label className="block space-y-2">
              <span className="font-medium">{t("space_copy_ui.name")}</span>
              <Input
                value={name}
                maxLength={200}
                disabled={busy || Boolean(pending.current)}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <div className="space-y-2">
              <p className="font-medium">{t("space_copy_ui.scope_label")}</p>
              <p>{t("space_copy_ui.scope")}</p>
            </div>
            <div className="flex gap-2 rounded-md bg-blue-500/[0.07] p-3 text-body-sm text-text-2">
              <Outlined.Info className="size-4 shrink-0 text-blue-500" />
              <p>{t("space_copy_ui.permissions")}</p>
            </div>
            <p className="text-text-3">{t("space_copy_ui.independent")}</p>
          </div>
        ) : (
          <div className="space-y-4 py-2">
            <p>
              {t(completed ? "space_copy_ui.created" : "copying", {
                name: result.knowledge.name,
              })}
            </p>
            {result.processing_job && !completed && (
              <SpaceProcessingProgress
                scope={scope}
                spaceId={result.knowledge.id}
                jobId={result.processing_job.job_id}
                kind="space_copy"
                onCompleted={() => {
                  setCompleted(true);
                  void Promise.resolve(onCreated()).catch(showApiError);
                }}
              />
            )}
          </div>
        )}
      </SpacePanelFrame>
    </Dialog>
  );
}
