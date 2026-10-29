import { createPortal } from "react-dom";
import { Button } from '@bisheng/ui';
import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect";

import { userContext } from "@/contexts/userContext";
import {
  getDshUsagePresentationOverview as getDshUsageOverview,
  getDshUsagePresentationSummary as getDshUsageTimeSummary,
} from "@/controllers/API/dshUsagePresentation";
import type { DshUsageOverviewUser, DshUsageTimeSummary } from "@/types/dsh";
import { Segmented } from "@bisheng/ui";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { UsageRangeSelect } from "./UsageRangeSelect";
import { UsageSummaryView } from "./UsageSummaryView";
import { UsageUserSelect } from "./UsageUserSelect";
import { usageGranularity, usagePresetRange, type UsagePreset, type UsageRange } from "./usageRange";

type Dimension = "user" | "department";

export function PolicyView({ toolbarTarget }: { toolbarTarget?: HTMLDivElement | null }) {
  const { t } = useTranslation();
  const { user: currentUser } = useContext(userContext);
  const [dimension, setDimension] = useState<Dimension>("user");
  const [department, setDepartment] = useState<{ id: number; name: string } | null>(null);
  const [user, setUser] = useState<DshUsageOverviewUser | null>(null);
  const [preset, setPreset] = useState<UsagePreset>("year");
  const [selectedRange, setRange] = useState<UsageRange>(() => usagePresetRange("year"));
  const range = useMemo(() => selectedRange, [selectedRange]);
  const [summary, setSummary] = useState<DshUsageTimeSummary | null>(null);
  const [error, setError] = useState(false);
  const [defaultUserLoading, setDefaultUserLoading] = useState(true);
  const [defaultUserError, setDefaultUserError] = useState(false);
  const targetId = dimension === "department" ? department?.id : user?.user_id;
  const hasTarget = dimension === "department" || !!user;
  const tenantLabel = [currentUser?.tenant_name || currentUser?.leaf_tenant_name, t("dsh.entireTenant")]
    .filter(Boolean)
    .join(" / ");

  useEffect(() => {
    if (dimension !== "user" || user) return;
    const abort = new AbortController();
    setDefaultUserLoading(true);
    setDefaultUserError(false);
    const loadDefaultUser = async () => {
      const page = await getDshUsageOverview({ ...range, limit: 20 }, abort.signal);
      let preferred =
        page.items.find((item) => item.user_name === "admin") ??
        page.items.find((item) => item.user_id === Number(currentUser?.user_id));
      if (!preferred && currentUser?.user_name && page.has_more) {
        const matches = await getDshUsageOverview(
          { ...range, keyword: currentUser.user_name, limit: 100 },
          abort.signal,
        );
        preferred = matches.items.find((item) => item.user_id === Number(currentUser.user_id));
      }
      if (!abort.signal.aborted) setUser((selected) => selected ?? preferred ?? page.items[0] ?? null);
    };
    loadDefaultUser()
      .catch(() => {
        if (!abort.signal.aborted) setDefaultUserError(true);
      })
      .finally(() => {
        if (!abort.signal.aborted) setDefaultUserLoading(false);
      });
    return () => abort.abort();
  }, [dimension, user, currentUser?.user_id, currentUser?.user_name, range]);

  useEffect(() => {
    const abort = new AbortController();
    setSummary(null);
    setError(false);
    if (!hasTarget) return;
    const request =
      dimension === "department"
        ? getDshUsageOverview(
            {
              ...range,
              granularity: usageGranularity(range),
              departmentId: targetId,
              limit: 20,
              includeSummary: true,
            },
            abort.signal,
          ).then((result) => result.summary ?? null)
        : getDshUsageTimeSummary(String(targetId), { ...range, granularity: usageGranularity(range) }, abort.signal);
    request
      .then((result) => {
        if (!abort.signal.aborted) {
          setSummary(result);
          setError(!result);
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) setError(true);
      });
    return () => abort.abort();
  }, [dimension, targetId, hasTarget, range]);

  const handleUser = (next: DshUsageOverviewUser) => {
    setUser(next);
    setDimension("user");
  };
  const handleRange = (next: UsagePreset, nextRange: UsageRange) => {
    setPreset(next);
    setRange(nextRange);
  };
  const toolbar = (
    <div className="flex min-w-0 flex-wrap items-center gap-2" aria-label={t("dsh.usageFilters")}>
      <Segmented
        aria-label={t("dsh.usageDimension")}
        value={dimension}
        onChange={(value) => setDimension(value as Dimension)}
        options={[
          { value: "department", label: t("dsh.byDepartment") },
          { value: "user", label: t("dsh.byUser") },
        ]}
      />
      {dimension === "department" ? (
        <TreeDepartmentSelect
          allowNone
          noneLabel={tenantLabel}
          value={department?.id ?? null}
          onChange={(id, node) => {
            setDepartment(id && node ? { id, name: node.name } : null);
          }}
          placeholder={t("dsh.selectDepartment")}
          searchPlaceholder={t("dsh.searchDepartments")}
          modal={false}
          className="w-72 max-w-full"
          triggerClassName="input-touch-hit h-8 gap-2 overflow-hidden rounded-md border-border-base bg-bg-page px-[11px] text-[length:var(--font-size-3)] leading-[var(--line-height-3)] text-text-1 shadow-none hover:border-border-deep hover:bg-bg-page focus-visible:border-border-deep focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:shadow-focus data-[state=open]:border-border-deep data-[state=open]:shadow-focus [&>svg]:ml-0 [&>svg]:size-4 [&>svg]:text-text-3 [&>svg]:opacity-100 [&>svg]:transition-transform [&[data-state=open]>svg]:rotate-180"
        />
      ) : (
        <UsageUserSelect value={user} range={range} onChange={handleUser} />
      )}
      <UsageRangeSelect preset={preset} onChange={handleRange} />
    </div>
  );

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbar}
        <Button size="medium" variant="outlined" onClick={() => setRange(usagePresetRange(preset))} color="default">
          {t("dsh.refresh")}
        </Button>
      </div>
      {!hasTarget ? (
        <div
          role={defaultUserError ? "alert" : "status"}
          className="rounded-lg border p-10 text-center text-sm text-muted-foreground"
        >
          {t(defaultUserError ? "dsh.unavailable" : defaultUserLoading ? "dsh.loading" : "dsh.empty")}
        </div>
      ) : (
        <>
          {summary ? (
            <UsageSummaryView summary={summary} />
          ) : (
            <p role={error ? "alert" : "status"} className="py-8 text-sm text-muted-foreground">
              {t(error ? "dsh.usageRangeUnavailable" : "dsh.loading")}
            </p>
          )}
        </>
      )}
    </section>
  );
}
