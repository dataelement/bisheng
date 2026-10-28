import { Button } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import type { ModelAuditQuery } from "@/types/dshModelAudit";
import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DshChoice } from "./common";
import { ModelAuditModelSelect } from "./ModelAuditModelSelect";
import { ModelAuditTimeRange, validAuditRange } from "./ModelAuditTimeRange";
import { ModelAuditUserSelect } from "./ModelAuditUserSelect";

const advancedKeys = [
  "request_id",
  "conversation_id",
  "model_name",
  "audit_status",
] as const;
interface ModelAuditFiltersProps {
  pending: boolean;
  tenantId?: number;
  draft: ModelAuditQuery;
  statusReady?: boolean;
  nameReady?: boolean;
  onChange: (changes: Partial<ModelAuditQuery>) => void;
  onApply: () => void;
  onReset: () => void;
}
export function ModelAuditFilters({
  pending,
  tenantId,
  draft,
  statusReady = false,
  nameReady = false,
  onChange,
  onApply,
  onReset,
}: ModelAuditFiltersProps) {
  const { t } = useTranslation();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const count = advancedKeys.filter(
    (key) => draft[key] !== undefined && draft[key] !== "",
  ).length;
  const validRange = validAuditRange(draft.start_at, draft.end_at);
  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (
          validRange &&
          (!draft.model_name || nameReady) &&
          (!draft.audit_status || statusReady)
        )
          onApply();
      }}
    >
      <div className="grid min-w-0 items-end gap-3 md:grid-cols-[minmax(140px,1fr)_minmax(220px,1.3fr)_auto]">
        <ModelAuditUserSelect
          tenantId={tenantId}
          value={draft.user_id}
          onChange={(userId) =>
            onChange({ user_id: userId, user_keyword: undefined })
          }
        />
        <ModelAuditTimeRange
          startAt={draft.start_at}
          endAt={draft.end_at}
          onChange={onChange}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="submit"
            disabled={
              (!!draft.model_name && !nameReady) ||
              (!!draft.audit_status && !statusReady)
            }
            size="small"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
          >
            {t("dsh.modelAuditView.search")}
          </Button>
          <Button
            type="button"
            size="small"
            variant="outlined" color="default"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
            onClick={onReset}
          >
            {t("dsh.modelAuditView.resetFilters")}
          </Button>
          <Button
            type="button"
            size="small"
            variant="text" color="default"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
            aria-expanded={advancedOpen}
            aria-controls="audit-advanced-filters"
            onClick={() => setAdvancedOpen((old) => !old)}
          >
            <Outlined.Filter className="mr-2 size-4" aria-hidden="true" />
            {t("dsh.modelAuditView.advancedFilters")}
            {count ? " (" + count + ")" : ""}
          </Button>
        </div>
      </div>
      {pending && (
        <p role="status" className="text-xs text-muted-foreground">
          {t("dsh.modelAuditView.pending_filters")}
        </p>
      )}
      {!validRange && (
        <p
          id="audit-time-error"
          role="alert"
          className="text-sm text-destructive"
        >
          {t("dsh.modelAuditView.invalid_time_range")}
        </p>
      )}
      {advancedOpen && (
        <div
          id="audit-advanced-filters"
          className="space-y-3 rounded-xl bg-muted/50 p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              {t("dsh.modelAuditView.advanced_hint")}
            </p>
            <Button
              type="button"
              size="small"
              variant="text" color="default"
              className="text-sm [@media(pointer:coarse)]:min-h-11"
              onClick={() =>
                onChange(
                  Object.fromEntries(
                    advancedKeys.map((key) => [key, undefined]),
                  ),
                )
              }
            >
              {t("dsh.modelAuditView.clear_advanced")}
            </Button>
          </div>
          <div className="grid items-start gap-3 md:grid-cols-2">
            <ModelAuditModelSelect
              tenantId={tenantId}
              value={draft.model_name}
              onChange={onChange}
            />
            <div className="space-y-1 [&_button]:w-full">
              <span className="block text-xs text-muted-foreground">
                {t("dsh.modelAuditView.summary_status")}
              </span>
              {statusReady ? (
                <DshChoice
                  label={t("dsh.modelAuditView.summary_status")}
                  value={draft.audit_status || "ALL"}
                  options={["ALL", "NORMAL", "ABNORMAL"].map((value) => ({
                    value,
                    label: t("dsh.modelAuditView.summary." + value),
                  }))}
                  onChange={(value) =>
                    onChange({
                      audit_status:
                        value === "ALL"
                          ? undefined
                          : (value as "NORMAL" | "ABNORMAL"),
                    })
                  }
                />
              ) : (
                <p className="py-2 text-sm text-muted-foreground">
                  {t("dsh.modelAuditView.index_preparing")}
                </p>
              )}
            </div>
            {(["request_id", "conversation_id"] as const).map((key) => (
              <label key={key} htmlFor={"audit-" + key} className="space-y-1">
                <span className="block text-xs text-muted-foreground">
                  {t("dsh.modelAuditView.filters." + key)}
                </span>
                <Input
                  id={"audit-" + key}
                  aria-label={t("dsh.modelAuditView.filters." + key)}
                  value={draft[key] || ""}
                  maxLength={key === "request_id" ? 36 : 256}
                  className="[@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-base"
                  onChange={(event) =>
                    onChange({ [key]: event.target.value || undefined })
                  }
                />
              </label>
            ))}
          </div>
        </div>
      )}
    </form>
  );
}
