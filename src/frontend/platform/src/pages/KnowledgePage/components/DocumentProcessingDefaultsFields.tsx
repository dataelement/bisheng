import { Checkbox, InputNumber } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useId, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/bs-ui/label";
import type { DocumentProcessingRule } from "@/controllers/API/knowledgeSpace";
import { cn } from "@/utils";

type DocumentNumberField =
  "chunk_size" | "chunk_overlap" | "hierarchy_level" | "max_chunk_size";
export type DocumentProcessingDefaultsDraft = Omit<
  DocumentProcessingRule,
  DocumentNumberField
> &
  Record<DocumentNumberField, number | null>;
interface DocumentProcessingDefaultsFieldsProps {
  value: DocumentProcessingDefaultsDraft;
  onChange: (value: DocumentProcessingDefaultsDraft) => void;
  disabled?: boolean;
  children?: ReactNode;
  compact?: boolean;
}

/** Default drafts are controlled separately from the legacy upload state. */
export function DocumentProcessingDefaultsFields({
  value,
  onChange,
  disabled = false,
  children,
  compact = false,
}: DocumentProcessingDefaultsFieldsProps) {
  const { t } = useTranslation("knowledge");
  const id = useId();
  const flags = [
    ["retain_images", "keepImages"],
    ["force_ocr", "ocrForce"],
    ["enable_formula", "enableRec"],
    ["filter_page_header_footer", "hfFilter"],
  ] as const;
  const modes = ["auto", "custom", "hierarchical"] as const;
  const fields: {
    key: DocumentNumberField;
    label: string;
    min: number;
    max?: number;
    unit: string;
  }[] =
    value.split_mode === "hierarchical"
      ? [
          {
            key: "hierarchy_level",
            label: "splitLevel",
            min: 1,
            max: 6,
            unit: "layer",
          },
          {
            key: "max_chunk_size",
            label: "maxChunkSize",
            min: 1,
            unit: "characters",
          },
        ]
      : [
          {
            key: "chunk_size",
            label: "splitLength",
            min: 1,
            unit: "characters",
          },
          {
            key: "chunk_overlap",
            label: "chunkOverlap",
            min: 0,
            unit: "characters",
          },
        ];
  return (
    <fieldset disabled={disabled} className={cn("space-y-6", compact && "min-w-0")}>
      <div className="space-y-4">
        <h3 className="text-base font-medium">{t("docAnalysisStrategy")}</h3>
        <div className="space-y-4 rounded-lg border border-border-base p-4">
          <p className="text-sm text-text-3">{t("pdfOptionsHint")}</p>
          <div className="flex flex-wrap gap-x-8 gap-y-3">
            {flags.map(([key, label]) => (
              <div key={key} className="flex items-center gap-2">
                <Checkbox
                  id={`${id}-${key}`}
                  checked={value[key] === 1}
                  disabled={disabled}
                  onCheckedChange={(checked) =>
                    onChange({ ...value, [key]: checked === true ? 1 : 0 })
                  }
                />
                <Label htmlFor={`${id}-${key}`}>{t(label)}</Label>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="space-y-4">
        <h3 className="text-base font-medium">{t("docSplitStrategy")}</h3>
        <div
          role="radiogroup"
          aria-label={t("docSplitStrategy")}
          className={cn(
            "grid gap-4",
            compact ? "grid-cols-[repeat(auto-fit,minmax(min(100%,10rem),1fr))]" : "lg:grid-cols-3",
          )}
        >
          {modes.map((mode) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={value.split_mode === mode}
              disabled={disabled}
              onClick={() => onChange({ ...value, split_mode: mode })}
              className={cn(
                "flex min-h-[100px] flex-col rounded-lg border p-4 text-left disabled:cursor-not-allowed disabled:opacity-50",
                compact && "min-w-0 break-words",
                value.split_mode === mode
                  ? "border-primary bg-primary/5"
                  : "border-border-base hover:bg-fill-1",
              )}
            >
              <span className="mb-1 flex w-full items-center justify-between text-sm font-medium">
                {t(`${mode}Split`)}
                {value.split_mode === mode ? (
                  <Outlined.CheckCircle className={cn("size-5 text-primary", compact && "shrink-0")} />
                ) : (
                  <Outlined.Round className={cn("size-5 text-text-4", compact && "shrink-0")} />
                )}
              </span>
              <span className="text-sm text-text-3">
                {t(`${mode}SplitDesc`)}
              </span>
            </button>
          ))}
        </div>
        {value.split_mode !== "auto" && (
          <div className="space-y-6 rounded-lg border border-border-base p-5">
            <div className="flex flex-wrap gap-x-8 gap-y-4">
              {fields.map(({ key, label, min, max, unit }) => (
                <div key={key} className={cn("flex items-center gap-3", compact && "min-w-0 max-w-full flex-wrap")}>
                  <Label
                    htmlFor={`${id}-${key}`}
                    className={cn("text-sm text-text-2", !compact && "whitespace-nowrap")}
                  >
                    {t(label)}
                  </Label>
                  <InputNumber
                    id={`${id}-${key}`}
                    aria-label={t(label)}
                    className={cn("w-48", compact && "min-w-0 max-w-full")}
                    suffix={t(unit)}
                    value={value[key]}
                    min={min}
                    max={max}
                    precision={0}
                    disabled={disabled}
                    onChange={(number) => onChange({ ...value, [key]: number })}
                    increaseLabel={t("bs:sharedUi.increase")}
                    decreaseLabel={t("bs:sharedUi.decrease")}
                    errorMessage={() =>
                      t(
                        max === undefined
                          ? "f118.integer_at_least"
                          : "f118.integer_between",
                        { min, max },
                      )
                    }
                  />
                </div>
              ))}
            </div>
            {value.split_mode === "hierarchical" && (
              <div className="flex items-center gap-2">
                <Checkbox
                  id={`${id}-append`}
                  checked={value.append_title}
                  disabled={disabled}
                  onCheckedChange={(checked) =>
                    onChange({ ...value, append_title: checked === true })
                  }
                />
                <Label htmlFor={`${id}-append`}>{t("appendTitle")}</Label>
              </div>
            )}
            {children}
          </div>
        )}
      </div>
    </fieldset>
  );
}
