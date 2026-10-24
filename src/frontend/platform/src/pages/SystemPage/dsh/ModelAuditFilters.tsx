import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { contentSafetyStates } from "@/types/dshContentSafety";
import type { ModelAuditQuery } from "@/types/dshModelAudit";
import { SlidersHorizontal } from "lucide-react";
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
  "has_sensitive_hit",
  "sensitive_direction",
  "content_safety_state",
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
  const rangeTooLarge =
    !!draft.start_at &&
    !!draft.end_at &&
    Date.parse(draft.end_at) - Date.parse(draft.start_at) > 31 * 86400000;
  const validRange =
    validAuditRange(draft.start_at, draft.end_at) && !rangeTooLarge;
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
              !validRange ||
              (!!draft.model_name && !nameReady) ||
              (!!draft.audit_status && !statusReady)
            }
            size="sm"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
          >
            {t("dsh.modelAuditView.search")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
            onClick={onReset}
          >
            {t("dsh.modelAuditView.resetFilters")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-sm [@media(pointer:coarse)]:min-h-11"
            aria-expanded={advancedOpen}
            aria-controls="audit-advanced-filters"
            onClick={() => setAdvancedOpen((old) => !old)}
          >
            <SlidersHorizontal className="mr-2 size-4" aria-hidden="true" />
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
          {t(
            rangeTooLarge
              ? "dsh.contentSafety.validation.range_too_large"
              : "dsh.modelAuditView.invalid_time_range",
          )}
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
              size="sm"
              variant="ghost"
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
            <div className="space-y-1 [&_button]:w-full">
              <span className="block text-xs text-muted-foreground">
                {t("dsh.contentSafety.filters.has_hit")}
              </span>
              <DshChoice
                label={t("dsh.contentSafety.filters.has_hit")}
                value={
                  draft.has_sensitive_hit === undefined
                    ? "ALL"
                    : String(draft.has_sensitive_hit)
                }
                options={[
                  { value: "ALL", label: t("dsh.contentSafety.filters.all") },
                  { value: "true", label: t("dsh.contentSafety.filters.hit") },
                  {
                    value: "false",
                    label: t("dsh.contentSafety.filters.no_known_hit"),
                  },
                ]}
                onChange={(value) =>
                  onChange({
                    has_sensitive_hit:
                      value === "ALL" ? undefined : value === "true",
                    cursor: undefined,
                  })
                }
              />
              {draft.has_sensitive_hit === false && (
                <p className="text-xs text-muted-foreground">
                  {t("dsh.contentSafety.filters.no_known_hit_hint")}
                </p>
              )}
            </div>
            <div className="space-y-1 [&_button]:w-full">
              <span className="block text-xs text-muted-foreground">
                {t("dsh.contentSafety.filters.direction")}
              </span>
              <DshChoice
                label={t("dsh.contentSafety.filters.direction")}
                value={draft.sensitive_direction || "ALL"}
                options={[
                  { value: "ALL", label: t("dsh.contentSafety.filters.all") },
                  ...(["INPUT", "OUTPUT", "BOTH"] as const).map((value) => ({
                    value,
                    label: t("dsh.contentSafety.directions." + value),
                  })),
                ]}
                onChange={(value) =>
                  onChange({
                    sensitive_direction: (
                      ["INPUT", "OUTPUT", "BOTH"] as const
                    ).find((direction) => direction === value),
                    cursor: undefined,
                  })
                }
              />
            </div>
            <div className="space-y-1 [&_button]:w-full">
              <span className="block text-xs text-muted-foreground">
                {t("dsh.contentSafety.filters.state")}
              </span>
              <DshChoice
                label={t("dsh.contentSafety.filters.state")}
                value={draft.content_safety_state || "ALL"}
                options={[
                  { value: "ALL", label: t("dsh.contentSafety.filters.all") },
                  ...contentSafetyStates.map((value) => ({
                    value,
                    label: t("dsh.contentSafety.states." + value),
                  })),
                ]}
                onChange={(value) =>
                  onChange({
                    content_safety_state: contentSafetyStates.find(
                      (state) => state === value,
                    ),
                    cursor: undefined,
                  })
                }
              />
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
