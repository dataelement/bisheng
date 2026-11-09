import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { Alert, Button } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { ModelRemovalView } from "./useModelRemoval";

interface ModelRemovalDialogProps {
  view: ModelRemovalView | null;
  onCancel: () => void;
  onConfirm: () => void;
  onForce: () => void;
  onRefresh: () => void;
  onLoadMore: () => void;
}

interface ModelConfigActionsProps {
  showDelete: boolean;
  writable: boolean;
  canSave: boolean;
  saving: boolean;
  active: boolean;
  onDelete: () => void;
  onCancel: () => void;
  onSave: () => void;
}

export function ModelConfigActions({
  showDelete,
  writable,
  canSave,
  saving,
  active,
  onDelete,
  onCancel,
  onSave,
}: ModelConfigActionsProps) {
  const { t } = useTranslation("model");
  const busy = saving || active;
  return (
    <div className="absolute right-0 bottom-0 p-4 flex gap-4">
      {showDelete && (
        <Button
          variant="outlined"
          color="danger"
          disabled={!writable || busy}
          onClick={onDelete}
        >
          {t("model.delete")}
        </Button>
      )}
      <Button
        variant="outlined"
        color="default"
        disabled={busy}
        onClick={onCancel}
      >
        {t("model.cancel")}
      </Button>
      <Button
        disabled={!canSave || !writable || busy}
        loading={saving}
        onClick={onSave}
      >
        {t(saving ? "bs:model.modelStatusChecking" : "model.save")}
      </Button>
    </div>
  );
}

export function ModelRemovalDialog({
  view,
  onCancel,
  onConfirm,
  onForce,
  onRefresh,
  onLoadMore,
}: ModelRemovalDialogProps) {
  const { t } = useTranslation("model");
  if (!view) return null;
  const inspection = view.result?.inspection;
  const blocked = inspection?.blocked === true;
  const frozen = view.pending || view.dispatched;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !frozen) onCancel();
      }}
    >
      <DialogContent
        close={false}
        onEscapeKeyDown={(event) => {
          if (frozen) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (frozen) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {t(
              view.kind === "delete"
                ? "model.removalDeleteTitle"
                : "model.removalUpdateTitle",
            )}
          </DialogTitle>
          <DialogDescription>{t("model.removalDescription")}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto space-y-4">
          {!inspection && view.pending && (
            <p role="status" className="text-sm">
              {t("model.removalChecking")}
            </p>
          )}
          {view.error && <Alert type="error" live description={view.error} />}
          {view.dispatched && !view.pending && (
            <Alert
              type="warning"
              description={t("model.removalRetrySameCommand")}
            />
          )}
          {inspection && (
            <>
              <p className="text-sm">
                {t("model.removalTargetCount", {
                  count: inspection.targets.length,
                })}
              </p>
              {blocked && (
                <Alert type="warning" description={t("model.removalBlocked")} />
              )}
              <ul className="space-y-2 text-sm">
                {inspection.source_counts
                  .filter(([, count]) => count > 0)
                  .map(([kind, count]) => {
                    const slots =
                      inspection.slot_counts.find(
                        ([key]) => key === kind,
                      )?.[1] ?? 0;
                    const restricted =
                      inspection.restricted_counts.find(
                        ([key]) => key === kind,
                      )?.[1] ?? 0;
                    return (
                      <li key={kind}>
                        <p>
                          {t(`model.removalSourceTypes.${kind}`)}:{" "}
                          {t("model.removalSourceCount", { count, slots })}
                        </p>
                        {restricted > 0 && (
                          <p className="text-muted-foreground">
                            {t("model.removalRestrictedCount", {
                              count: restricted,
                            })}
                          </p>
                        )}
                      </li>
                    );
                  })}
              </ul>
              {!!view.page?.data.length && (
                <ul className="space-y-2 rounded-md border p-3 text-sm">
                  {view.page.data.map(({ disclosure, matched_slot_count }) => {
                    const source = disclosure.source;
                    const entry =
                      disclosure.entry?.startsWith("/") &&
                      !disclosure.entry.startsWith("//")
                        ? disclosure.entry
                        : null;
                    return (
                      <li
                        key={`${source.source_type}:${source.tenant_id}:${source.source_id}:${source.source_version}`}
                      >
                        {entry ? (
                          <a
                            className="text-primary underline"
                            href={entry}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {disclosure.name}
                          </a>
                        ) : (
                          <span>{disclosure.name}</span>
                        )}
                        {disclosure.version_label && (
                          <span className="ml-2 text-muted-foreground">
                            {disclosure.version_label}
                          </span>
                        )}
                        <span className="ml-2 text-muted-foreground">
                          {t("model.removalSlotCount", {
                            count: matched_slot_count,
                          })}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
              {view.page?.has_more && !view.dispatched && (
                <Button
                  variant="outlined"
                  size="small"
                  disabled={view.pending}
                  loading={view.pending}
                  onClick={onLoadMore}
                >
                  {t("model.removalLoadMore")}
                </Button>
              )}
            </>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outlined"
            color="default"
            disabled={frozen}
            onClick={onCancel}
          >
            {t("model.cancel")}
          </Button>
          {!view.result ||
          view.needsRefresh ||
          (!view.dispatched && view.errorCode === 10994) ? (
            <Button
              disabled={view.pending}
              loading={view.pending}
              onClick={onRefresh}
            >
              {t("model.removalReviewAgain")}
            </Button>
          ) : (
            <>
              <Button
                color="danger"
                disabled={view.pending || (!view.dispatched && blocked)}
                loading={view.pending}
                onClick={onConfirm}
              >
                {t(
                  view.dispatched
                    ? "model.removalRetry"
                    : view.kind === "delete"
                      ? "model.removalConfirmDelete"
                      : "model.removalConfirmSave",
                )}
              </Button>
              {blocked && !view.dispatched && view.errorCode !== 10994 && (
                <Button
                  color="danger"
                  variant="outlined"
                  disabled={view.pending}
                  onClick={onForce}
                >
                  {t("model.removalForce")}
                </Button>
              )}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
