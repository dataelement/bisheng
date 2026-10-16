import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import {
  contentStates,
  modelResults,
  responseResults,
  settlements,
} from "@/types/dshModelAudit";
import type { ModelAuditQuery } from "@/types/dshModelAudit";
import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DshChoice } from "./common";
import { ModelAuditModelSelect } from "./ModelAuditModelSelect";
import { ModelAuditTimeRange, validAuditRange } from "./ModelAuditTimeRange";
import { ModelAuditUserSelect } from "./ModelAuditUserSelect";

const debugTextFilters = [
  "request_id",
  "conversation_id",
  "provider_name",
] as const;
const axes = [
  ["model_result", modelResults],
  ["response_result", responseResults],
  ["usage_settlement", settlements],
  ["content_status", contentStates],
] as const;
const advancedKeys = [
  ...debugTextFilters,
  ...axes.map(([key]) => key),
  "association_status" as const,
];

interface ModelAuditFiltersProps {
  pending: boolean;
  tenantId?: number;
  draft: ModelAuditQuery;
  onChange: (changes: Partial<ModelAuditQuery>) => void;
  onApply: () => void;
  onReset: () => void;
}
export function ModelAuditFilters({
  pending,
  tenantId,
  draft,
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
        if (validRange) onApply();
      }}
    >
      <div className="grid min-w-0 items-end gap-3 md:grid-cols-3 xl:grid-cols-[minmax(140px,.8fr)_minmax(220px,1.3fr)_minmax(220px,1.2fr)_auto]">
        <ModelAuditUserSelect
          tenantId={tenantId}
          value={draft.user_id}
          onChange={(userId) =>
            onChange({ user_id: userId, user_keyword: undefined })
          }
        />
        <ModelAuditModelSelect
          tenantId={tenantId}
          modelId={draft.model_id}
          value={draft.model_name}
          onChange={onChange}
        />
        <ModelAuditTimeRange
          startAt={draft.start_at}
          endAt={draft.end_at}
          onChange={onChange}
        />
        <div className="flex flex-wrap items-center gap-2 md:col-span-3 xl:col-span-1">
          <Button
            type="submit"
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
            {count ? ` (${count})` : ""}
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
          className="space-y-3 rounded-lg bg-muted/50 p-4"
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
          <div className="grid gap-3 md:grid-cols-3">
            {debugTextFilters.map((key) => (
              <label
                key={key}
                htmlFor={"audit-" + key}
                className="min-w-0 space-y-1"
              >
                <span className="block text-xs text-muted-foreground">
                  {t("dsh.modelAuditView.filters." + key)}
                </span>
                <Input
                  id={"audit-" + key}
                  aria-label={t("dsh.modelAuditView.filters." + key)}
                  value={draft[key] || ""}
                  maxLength={
                    key === "conversation_id"
                      ? 256
                      : key === "request_id"
                        ? 36
                        : 128
                  }
                  className="[@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-base"
                  onChange={(event) =>
                    onChange({ [key]: event.target.value || undefined })
                  }
                />
              </label>
            ))}
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {axes.map(([key, choices]) => (
              <div
                key={key}
                className="min-w-0 space-y-1 [&_button]:w-full [&_button]:min-w-0 [&_button]:[@media(pointer:coarse)]:min-h-11"
              >
                <span className="block text-xs text-muted-foreground">
                  {t("dsh.modelAuditView.axes." + key)}
                </span>
                <DshChoice
                  label={t("dsh.modelAuditView.axes." + key)}
                  value={draft[key] || "ALL"}
                  options={[
                    { value: "ALL", label: t("dsh.modelAuditView.all") },
                    ...choices.map((value) => ({
                      value,
                      label: t("dsh.modelAuditView.states." + value),
                    })),
                  ]}
                  onChange={(value) =>
                    onChange({ [key]: value === "ALL" ? undefined : value })
                  }
                />
              </div>
            ))}
            <div className="min-w-0 space-y-1 [&_button]:w-full [&_button]:min-w-0 [&_button]:[@media(pointer:coarse)]:min-h-11">
              <span className="block text-xs text-muted-foreground">
                {t("dsh.modelAuditView.association")}
              </span>
              <DshChoice
                label={t("dsh.modelAuditView.association")}
                value={draft.association_status || "ALL"}
                options={(["ALL", "ASSOCIATED", "UNASSOCIATED"] as const).map(
                  (value) => ({
                    value,
                    label: t("dsh.modelAuditView.states." + value),
                  }),
                )}
                onChange={(value) =>
                  onChange({
                    association_status:
                      value === "ALL"
                        ? undefined
                        : (value as "ASSOCIATED" | "UNASSOCIATED"),
                  })
                }
              />
            </div>
          </div>
        </div>
      )}
    </form>
  );
}
