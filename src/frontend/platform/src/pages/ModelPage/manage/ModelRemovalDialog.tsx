import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { Table } from "@/components/bs-ui/table";
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

const referenceTableClassName =
  "min-w-[24rem] border-collapse text-text-1 [&_td]:h-10 [&_td]:p-2 [&_th]:h-10 [&_th]:p-2 [&_thead]:text-body-sm [&_tbody]:text-body-sm";

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
  const sourceCounts =
    inspection?.source_counts.filter(([, count]) => count > 0) ?? [];
  const slotCounts = new Map(inspection?.slot_counts);
  const restrictedCounts = new Map(inspection?.restricted_counts);
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
        className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-2xl grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto] sm:max-h-[calc(100dvh-4rem)]"
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
        <div className="min-h-0 max-h-[60vh] space-y-4 overflow-y-auto">
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
              {sourceCounts.length > 0 && (
                <Table
                  aria-label={t("model.removalReferenceSummary")}
                  className={referenceTableClassName}
                >
                  <thead className="bg-fill-1">
                    <tr>
                      <th scope="col" className="text-left font-medium">
                        {t("model.removalSourceType")}
                      </th>
                      <th scope="col" className="text-right font-medium">
                        {t("model.removalSourceCount")}
                      </th>
                      <th scope="col" className="text-right font-medium">
                        {t("model.removalRestrictedCount")}
                      </th>
                      <th scope="col" className="text-right font-medium">
                        {t("model.removalSlotCount")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sourceCounts.map(([kind, count]) => (
                      <tr key={kind} className="even:bg-fill-1/60">
                        <th scope="row" className="text-left font-normal">
                          {t(`model.removalSourceTypes.${kind}`)}
                        </th>
                        <td className="text-right tabular-nums">{count}</td>
                        <td className="text-right tabular-nums">
                          {restrictedCounts.get(kind) ?? 0}
                        </td>
                        <td className="text-right tabular-nums">
                          {slotCounts.get(kind) ?? 0}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
              {!!view.page?.data.length && (
                <Table
                  aria-label={t("model.removalReferenceDetails")}
                  className={`${referenceTableClassName} table-fixed`}
                >
                  <thead className="bg-fill-1">
                    <tr>
                      <th scope="col" className="w-2/5 text-left font-medium">
                        {t("model.removalSourceName")}
                      </th>
                      <th scope="col" className="w-1/4 text-left font-medium">
                        {t("model.removalSourceType")}
                      </th>
                      <th scope="col" className="w-[15%] text-left font-medium">
                        {t("model.removalSourceVersion")}
                      </th>
                      <th scope="col" className="w-1/5 text-right font-medium">
                        {t("model.removalSlotCount")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.page.data.map(({ disclosure, matched_slot_count }) => {
                      const source = disclosure.source;
                      const entry =
                        disclosure.entry?.startsWith("/") &&
                        !disclosure.entry.startsWith("//")
                          ? disclosure.entry
                          : null;
                      return (
                        <tr
                          key={`${source.source_type}:${source.tenant_id}:${source.source_id}:${source.source_version}`}
                          className="even:bg-fill-1/60"
                        >
                          <th
                            scope="row"
                            className="break-words text-left font-normal"
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
                              disclosure.name
                            )}
                          </th>
                          <td>
                            {t(`model.removalSourceTypes.${source.source_type}`)}
                          </td>
                          <td className="break-words">
                            {disclosure.version_label || "—"}
                          </td>
                          <td className="text-right tabular-nums">
                            {matched_slot_count}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
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
