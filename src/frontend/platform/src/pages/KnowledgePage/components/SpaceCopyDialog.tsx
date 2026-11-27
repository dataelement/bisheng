import { Alert, Button, Input } from "@bisheng/ui";
import { isApiError } from "@bisheng/api-client";
import { isValidSpaceName, SPACE_NAME_LIMIT, spaceNameLength, truncateSpaceName } from "@bisheng/knowledge";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog } from "@/components/bs-ui/dialog";
import {
  precheckSpaceCopy,
  confirmSpaceCopy,
  type ProcessingCreateRequest,
} from "@/controllers/API/knowledgeProcessing";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { createDshOperationId } from "@/util/dshOperationId";
import { SpacePanelFrame } from "./SpacePanelFrame";

interface SpaceCopyDialogProps {
  scope: KnowledgeQueryScope;
  source: KnowledgeSpaceInfo;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}
export function SpaceCopyDialog({
  source,
  onClose,
  onCreated,
}: SpaceCopyDialogProps) {
  const { t } = useTranslation("knowledge");
  const suffix = t("copySuffix");
  const [name, setName] = useState(
    () => truncateSpaceName(source.name, Math.max(0, SPACE_NAME_LIMIT - spaceNameLength(suffix))) + suffix,
  );
  const nameLength = spaceNameLength(name);
  const validName = isValidSpaceName(name);
  const [busy, setBusy] = useState(false);
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
    if (!alive.current || locked.current || !validName) return;
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
      await confirmSpaceCopy(source.id, pending.current);
      if (!alive.current) return;
      await onCreated();
      pending.current = null;
      onClose();
    } catch (error) {
      if (
        isApiError(error) &&
        (error.status_code === 18087 || error.status_code === 18088)
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
              {t("cancel")}
            </Button>
            <Button
              loading={busy}
              disabled={busy || !validName}
              onClick={() => {
                void handleCreate();
              }}
            >
              {t(pending.current ? "retry" : "space_copy_ui.create")}
            </Button>
          </>
        }
      >
        <div className="space-y-5 py-2 text-body">
            {pending.current && !busy && <p role="status">{t("space_copy_ui.retry_notice")}</p>}
            <label className="block space-y-2">
              <span className="font-medium">{t("space_copy_ui.name")}</span>
              <Input
                value={name}
                status={nameLength > SPACE_NAME_LIMIT ? "error" : undefined}
                suffix={`${nameLength}/${SPACE_NAME_LIMIT}`}
                disabled={busy || Boolean(pending.current)}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <div className="space-y-2">
              <p className="font-medium">{t("space_copy_ui.scope_label")}</p>
              <p>{t("space_copy_ui.scope")}</p>
            </div>
            <Alert type="info" className="mx-0 !mt-3" description={t("space_copy_ui.permissions")} />
            <p className="text-text-3">{t("space_copy_ui.independent")}</p>
          </div>
      </SpacePanelFrame>
    </Dialog>
  );
}
