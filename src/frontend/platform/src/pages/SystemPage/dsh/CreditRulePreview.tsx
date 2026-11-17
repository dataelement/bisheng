import { getUserCredits, type MonthCredits } from "@/controllers/API/modelPricing";
import { isValidMonthlyCredits } from "@/utils/dshCreditAmount";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface CreditRulePreviewProps {
  userId: number;
  credits: string;
  enabled: boolean;
}

/**
 * F016: what the member's month balance becomes if their own rule is saved as typed. The server
 * applies the same "highest matching rule" as billing, so a higher department or role shows here.
 */
export function CreditRulePreview({ userId, credits, enabled }: CreditRulePreviewProps) {
  const { t, i18n } = useTranslation();
  const [preview, setPreview] = useState<MonthCredits | null>(null);
  useEffect(() => {
    setPreview(null);
    if (!isValidMonthlyCredits(credits)) return undefined;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      getUserCredits(userId, abort.signal, { monthly_credits: credits, enabled })
        .then((value) => {
          if (!abort.signal.aborted) setPreview(value);
        })
        .catch(() => undefined);
    }, 300);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [userId, credits, enabled]);
  if (!preview || preview.used == null) return null;

  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const used = Number(preview.used);
  const limit = Number(preview.limit);
  if (preview.unlimited) {
    return (
      <p role="status" className="max-w-xs text-xs text-muted-foreground">
        {t("dsh.unified.previewUnlimited", { used: number.format(used) })}
      </p>
    );
  }
  const overdrawn = used > limit;
  return (
    <p role="status" className={`max-w-xs text-xs ${overdrawn ? "text-amber-600" : "text-muted-foreground"}`}>
      {t("dsh.unified.previewBalance", {
        used: number.format(used),
        remaining: number.format(Number(preview.remaining)),
        limit: number.format(limit),
      })}
      {enabled && limit !== Number(credits) && ` ${t("dsh.unified.previewHigherRule", { limit: number.format(limit) })}`}
      {overdrawn && ` ${t("dsh.unified.previewOverdrawn", { used: number.format(used) })}`}
    </p>
  );
}
