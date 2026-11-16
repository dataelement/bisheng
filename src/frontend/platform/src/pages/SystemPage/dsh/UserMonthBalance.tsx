import { getUserCredits } from "@/controllers/API/modelPricing";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { USER_CREDITS_QUERY_KEY } from "./UserCreditsCard";

interface UserMonthBalanceProps {
  userId: number;
  /** The allowance written on this user's own rule, to point out a higher department or role. */
  ruleCredits: string;
  ruleEnabled: boolean;
}

/**
 * F016: "used this month" and "left this month" cells of a per-user allowance row, so the
 * administrator sees an exhausted or overdrawn member before changing the allowance.
 */
export function UserMonthBalance({ userId, ruleCredits, ruleEnabled }: UserMonthBalanceProps) {
  const { t, i18n } = useTranslation();
  const query = useQuery({
    queryKey: [USER_CREDITS_QUERY_KEY, userId],
    queryFn: ({ signal }) => getUserCredits(userId, signal),
    retry: false,
    staleTime: 30_000,
  });
  const credits = query.data;
  if (!credits || credits.used == null) {
    const placeholder = query.isLoading ? "…" : "—";
    return (
      <>
        <td className="tabular-nums text-muted-foreground">{placeholder}</td>
        <td className="tabular-nums text-muted-foreground">{placeholder}</td>
      </>
    );
  }
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const used = Number(credits.used);
  const limit = Number(credits.limit);
  const overdrawn = !credits.unlimited && used > limit;
  return (
    <>
      <td className="tabular-nums">{number.format(used)}</td>
      <td className="tabular-nums">
        {credits.unlimited ? t("dsh.unified.creditsUnlimited") : number.format(Number(credits.remaining))}
        {overdrawn && (
          <span className="block text-xs text-amber-600">
            {t("dsh.unified.overdrawnBy", { amount: number.format(used - limit) })}
          </span>
        )}
        {!credits.unlimited && ruleEnabled && limit !== Number(ruleCredits) && (
          <span className="block text-xs text-muted-foreground">
            {t("dsh.unified.effectiveLimit", { limit: number.format(limit) })}
          </span>
        )}
      </td>
    </>
  );
}
