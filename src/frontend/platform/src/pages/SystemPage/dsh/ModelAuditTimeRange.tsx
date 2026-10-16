import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { CalendarDays, ChevronDown } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

export function validAuditRange(start?: string, end?: string) {
  return (
    (!start || Number.isFinite(Date.parse(start))) &&
    (!end || Number.isFinite(Date.parse(end))) &&
    (!start || !end || Date.parse(start) < Date.parse(end))
  );
}
function localDateTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
interface ModelAuditTimeRangeProps {
  startAt?: string;
  endAt?: string;
  onChange: (changes: { start_at?: string; end_at?: string }) => void;
}
export function ModelAuditTimeRange({
  startAt,
  endAt,
  onChange,
}: ModelAuditTimeRangeProps) {
  const { t } = useTranslation();
  const details = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  useEffect(() => {
    const handleOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !details.current?.contains(event.target) &&
        details.current
      )
        details.current.open = false;
    };
    document.addEventListener("pointerdown", handleOutside);
    return () => document.removeEventListener("pointerdown", handleOutside);
  }, []);
  const handleClose = () => {
    if (details.current) details.current.open = false;
    trigger.current?.focus();
  };
  const valid = validAuditRange(startAt, endAt);
  const label =
    !startAt && !endAt
      ? t("dsh.modelAuditView.all_time")
      : `${localDateTime(startAt).replace("T", " ") || t("dsh.modelAuditView.no_start")} — ${localDateTime(endAt).replace("T", " ") || t("dsh.modelAuditView.no_end")}`;
  return (
    <div className="min-w-0 space-y-1">
      <span className="block text-xs text-muted-foreground">
        {t("dsh.modelAuditView.time_range")}
      </span>
      <details
        ref={details}
        className="relative min-w-0"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            handleClose();
          }
        }}
      >
        <summary
          ref={trigger}
          aria-label={t("dsh.modelAuditView.time_range")}
          className="flex h-8 cursor-pointer list-none items-center gap-2 rounded-md border border-input bg-search-input px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden [@media(pointer:coarse)]:min-h-11"
        >
          <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate" title={label}>
            {label}
          </span>
          <ChevronDown className="size-4 shrink-0" aria-hidden="true" />
        </summary>
        <div className="relative mt-2 space-y-3 rounded-xl border bg-popover p-4 text-popover-foreground min-[576px]:absolute min-[576px]:right-0 min-[576px]:z-20 min-[576px]:mt-1 min-[576px]:w-80 min-[576px]:max-w-[calc(100vw-2rem)] min-[576px]:shadow-md">
          {(["start_at", "end_at"] as const).map((key) => (
            <label
              key={key}
              htmlFor={"audit-" + key}
              className="block space-y-1"
            >
              <span className="block text-xs text-muted-foreground">
                {t("dsh.modelAuditView.filters." + key)}
              </span>
              <Input
                id={"audit-" + key}
                type="datetime-local"
                aria-label={t("dsh.modelAuditView.filters." + key)}
                aria-invalid={!valid}
                aria-describedby={!valid ? "audit-time-error" : undefined}
                value={localDateTime(key === "start_at" ? startAt : endAt)}
                className="[@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:text-base"
                onChange={(event) =>
                  onChange({
                    [key]: event.target.value
                      ? new Date(event.target.value).toISOString()
                      : undefined,
                  })
                }
              />
            </label>
          ))}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="text-sm [@media(pointer:coarse)]:min-h-11"
              onClick={() =>
                onChange({ start_at: undefined, end_at: undefined })
              }
            >
              {t("dsh.modelAuditView.clear_time")}
            </Button>
            <Button
              type="button"
              size="sm"
              className="text-sm [@media(pointer:coarse)]:min-h-11"
              disabled={!valid}
              onClick={handleClose}
            >
              {t("dsh.modelAuditView.confirm_time")}
            </Button>
          </div>
        </div>
      </details>
    </div>
  );
}
