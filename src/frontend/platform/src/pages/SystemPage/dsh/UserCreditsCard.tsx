import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { getUserCredits } from "@/controllers/API/modelPricing";
import { Button } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

export const USER_CREDITS_QUERY_KEY = "dsh-admin-user-credits";

interface UserCreditsCardProps {
  userId: number;
}

/** The selected user's current-month credits; it follows the billing month, not the chart's range. */
export function UserCreditsCard({ userId }: UserCreditsCardProps) {
  const { t, i18n } = useTranslation();
  const query = useQuery({
    queryKey: [USER_CREDITS_QUERY_KEY, userId],
    queryFn: ({ signal }) => getUserCredits(userId, signal),
    retry: false,
  });
  const credits = query.data;
  if (!credits) {
    return (
      <p role={query.isError ? "alert" : "status"} className="flex items-center gap-2 text-sm text-muted-foreground">
        {query.isError ? t("dsh.unified.creditsUnavailable") : <LoadingState label={t("dsh.loading")} />}
        {query.isError && (
          <Button variant="link" size="small" className="h-auto px-0" onClick={() => void query.refetch()}>
            {t("dsh.refresh")}
          </Button>
        )}
      </p>
    );
  }

  // Fractions of a credit are billed, so two decimals keep small usage visible.
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const format = (value: string | null) => (value == null ? t("dsh.unavailable") : number.format(Number(value)));
  const resetDate = new Intl.DateTimeFormat(i18n.language, {
    month: "long",
    day: "numeric",
    timeZone: credits.billing_timezone,
  }).format(new Date(credits.reset_at));
  const unlimited = t("dsh.unified.creditsUnlimited");
  const figures = [
    { key: "used", label: t("dsh.unified.creditsUsed"), value: format(credits.used) },
    { key: "limit", label: t("dsh.unified.creditsLimit"), value: credits.unlimited ? unlimited : format(credits.limit) },
    {
      key: "remaining",
      label: t("dsh.unified.creditsRemaining"),
      value: credits.unlimited ? unlimited : format(credits.remaining),
    },
  ];
  return (
    <section className="space-y-3 rounded-lg border p-4" aria-labelledby="dsh-user-credits-title">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="dsh-user-credits-title" className="text-sm font-medium">
          {t("dsh.unified.monthCredits")}
        </h3>
        <span className="text-xs text-muted-foreground">{t("dsh.unified.creditsReset", { date: resetDate })}</span>
      </header>
      <dl className="flex flex-wrap gap-x-12 gap-y-3">
        {figures.map((figure) => (
          <div key={figure.key} data-credits={figure.key}>
            <dt className="text-sm text-muted-foreground">{figure.label}</dt>
            <dd className="mt-1 text-2xl font-medium tabular-nums">{figure.value}</dd>
          </div>
        ))}
      </dl>
      {!credits.unlimited && credits.used != null && Number(credits.used) > Number(credits.limit) && (
        <p role="status" className="text-xs text-amber-600">
          {t("dsh.unified.creditsOverdrawn", {
            amount: number.format(Number(credits.used) - Number(credits.limit)),
            used: format(credits.used),
          })}
        </p>
      )}
      <p className="text-xs text-muted-foreground">{t("dsh.unified.monthCreditsHelp")}</p>
    </section>
  );
}
