import { InputNumber, RadioGroup, Radio } from "@bisheng/ui";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export const enum LimitType {
  LIMITED = "limited",
  UNLIMITED = "unlimited",
}

interface FlowRadioProps {
  limit: number;
  onChange: (value: number) => void;
}

const MIN_LIMIT = 1;
const MAX_LIMIT = 9999;
const DEFAULT_LIMIT = 10;

export function FlowRadio({ limit, onChange }: FlowRadioProps) {
  const { t } = useTranslation("bs");
  const inputId = useId();
  const errorId = `${inputId}-error`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState(
    limit === 0 ? LimitType.UNLIMITED : LimitType.LIMITED
  );
  const [draft, setDraft] = useState<number | null>(limit || DEFAULT_LIMIT);
  const [showValidation, setShowValidation] = useState(false);

  const validationFor = (value: number | null) => {
    if (value === null) return t("sharedUi.required");
    if (value < MIN_LIMIT) return t("sharedUi.minimum", { min: MIN_LIMIT });
    if (value > MAX_LIMIT) return t("sharedUi.maximum", { max: MAX_LIMIT });
    if (!Number.isInteger(value)) return t("sharedUi.integer");
    return "";
  };
  const validationMessage = validationFor(draft);

  useEffect(() => {
    setStatus(limit === 0 ? LimitType.UNLIMITED : LimitType.LIMITED);
    setDraft(limit || DEFAULT_LIMIT);
    setShowValidation(false);
  }, [limit]);

  useEffect(() => {
    // Preserve invalid drafts while exposing them to the owning form's save guard.
    inputRef.current?.setCustomValidity(validationMessage);
  }, [status, validationMessage]);

  const handleTypeChange = (value: string) => {
    const next = value === LimitType.LIMITED ? DEFAULT_LIMIT : 0;
    setStatus(value as LimitType);
    setDraft(next || DEFAULT_LIMIT);
    setShowValidation(false);
    onChange(next);
  };

  const handleDraftChange = (value: number | null) => {
    const message = validationFor(value);
    setDraft(value);
    inputRef.current?.setCustomValidity(message);
    if (!message && value !== null) {
      setShowValidation(false);
      onChange(value);
    }
  };

  return (
    <RadioGroup
      size="medium"
      className="min-w-0 items-start min-[769px]:items-center"
      aria-label={t("system.flowCtrlStrategy")}
      value={status}
      onValueChange={handleTypeChange}
    >
      <div className="flex min-h-6 items-center">
        <Radio value={LimitType.UNLIMITED}>{t("system.unlimited")}</Radio>
      </div>
      <div className="flex min-h-6 min-w-0 flex-wrap items-center gap-2">
        <Radio value={LimitType.LIMITED}>{t("system.limit")}</Radio>
        {status === LimitType.LIMITED && (
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-field">
            <label htmlFor={inputId}>{t("system.maximum")}</label>
            <div className="w-28 max-w-full">
              <InputNumber
                ref={inputRef}
                id={inputId}
                size="small"
                value={draft}
                min={MIN_LIMIT}
                max={MAX_LIMIT}
                step={1}
                precision={0}
                required
                placeholder="1–9999"
                increaseLabel={t("sharedUi.increase")}
                decreaseLabel={t("sharedUi.decrease")}
                status={showValidation && validationMessage ? "error" : "default"}
                aria-invalid={showValidation && !!validationMessage || undefined}
                aria-describedby={showValidation && validationMessage ? errorId : undefined}
                onChange={handleDraftChange}
                onBlur={() => setShowValidation(Boolean(validationMessage))}
                onInvalid={() => setShowValidation(true)}
              />
              {showValidation && validationMessage && (
                <p id={errorId} className="mt-1 text-[length:var(--font-size-1)] leading-[var(--line-height-1)] text-danger">
                  {validationMessage}
                </p>
              )}
            </div>
            <span>{t("system.perMinute")}</span>
          </div>
        )}
      </div>
    </RadioGroup>
  );
}
