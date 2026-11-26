import { KnowledgeDialogTable } from "@bisheng/knowledge";
import { Button, Select } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import type { ItemState, ProcessingItemRead, ProcessingKind } from "@/controllers/API/knowledgeSpace";
import { processingFailureKey } from "./processingFailure";
import { SpaceProcessingLoading } from "./SpaceProcessingLoading";
import { SpaceProcessingStatus } from "./SpaceProcessingStatus";

const ITEM_STATES: readonly ItemState[] = ["pending", "running", "succeeded", "failed", "obsolete"];

interface SpaceProcessingItemsTableProps {
  caption?: string;
  emptyMessage?: string;
  items: readonly ProcessingItemRead[];
  kind?: ProcessingKind;
  filter?: ItemState;
  onFilterChange?: (state: ItemState | undefined) => void;
  showReasons?: boolean;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  fill?: boolean;
}

export function SpaceProcessingItemsTable({
  caption, emptyMessage, items, kind, filter, onFilterChange, showReasons = false, loading, failed, onRetry, fill = false,
}: SpaceProcessingItemsTableProps) {
  const { t } = useTranslation("knowledge");
  const selectLabels = useSelectLabels();
  const options = [
    { value: "all", label: t("all") },
    ...ITEM_STATES.map((state) => ({ value: state, label: t(`f118.processing_item_${state}`) })),
  ];
  const selectedLabel = filter ? t(`f118.processing_item_${filter}`) : t("all");
  return (
    <div className={fill ? "flex min-h-0 flex-1 flex-col" : "space-y-3"}>
      <KnowledgeDialogTable
        caption={caption ?? t("f118.processing_items")}
        showCaption={false}
        scrollable={fill}
        emptyContent={loading ? <SpaceProcessingLoading /> : failed ? (
          <Button variant="text" onClick={onRetry}>{t("retry")}</Button>
        ) : (
          <p className="py-6 text-center text-body text-text-3">
            {emptyMessage ?? t("f118.processing_no_matching_items")}
          </p>
        )}
        columns={[
          { label: t("f118.processing_item") },
          {
            label: t("status"),
            header: onFilterChange && (
              <span className="inline-flex items-center gap-1 whitespace-nowrap">
                {t("status")}
                <Select
                  {...selectLabels}
                  size="small"
                  variant="icon"
                  options={options}
                  value={filter ?? "all"}
                  onChange={(value) => {
                    if (value !== null) onFilterChange(value === "all" ? undefined : value as ItemState);
                  }}
                  trigger={
                    <Button
                      type="button"
                      variant="text"
                      color={filter ? "primary" : "default"}
                      size="small"
                      iconOnly
                      aria-label={`${t("f118.processing_filter_status")} · ${selectedLabel}`}
                    >
                      <Outlined.Filter aria-hidden />
                    </Button>
                  }
                />
              </span>
            ),
          },
          ...(showReasons ? [{ label: t("batch.column_reason") }] : []),
        ]}
        rows={items.map((item) => {
          const reasonKey = processingFailureKey(item, kind);
          return {
            key: item.id,
            cells: [
              item.file_name ?? t("f118.processing_file_id", { id: item.file_id }),
              <SpaceProcessingStatus
                state={item.state}
                label={t(`f118.processing_item_${item.state}`)}
                reasonKey={showReasons ? undefined : reasonKey}
              />,
              ...(showReasons ? [reasonKey ? t(reasonKey) : "—"] : []),
            ],
          };
        })}
      />
      {failed && items.length > 0 && (
        <Button className="shrink-0 self-start" variant="text" onClick={onRetry}>{t("retry")}</Button>
      )}
    </div>
  );
}
