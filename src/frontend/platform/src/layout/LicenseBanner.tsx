import { getLicenseStatus, LicenseStatus } from "@/controllers/API/license";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

// Severity → styling. Only warning/critical/expired render a banner; normal/unknown render nothing.
// expired/critical share red; warning is amber. See feature 037.
const SEVERITY_STYLE: Record<string, string> = {
    warning: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
    critical: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
    expired: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
};

const VISIBLE_SEVERITIES = ["warning", "critical", "expired"];

/**
 * Persistent top banner that surfaces the gateway license expiry state.
 *
 * Caller (MainLayout) gates this to super admins; this component additionally renders nothing
 * unless the severity is warning/critical/expired (so normal/unknown/unavailable stay silent).
 * Status comes from the gateway via getLicenseStatus(); open-source deployments have no gateway,
 * so it resolves to null and the banner stays hidden.
 */
export function LicenseBanner() {
    const { t } = useTranslation();
    const [status, setStatus] = useState<LicenseStatus | null>(null);

    useEffect(() => {
        let active = true;
        getLicenseStatus().then((res) => {
            if (active) setStatus(res);
        });
        return () => {
            active = false;
        };
    }, []);

    if (!status || !VISIBLE_SEVERITIES.includes(status.severity)) return null;

    const { severity, days_remaining } = status;
    const message =
        severity === "expired"
            ? t("license.expired")
            : t(`license.${severity}`, { days: days_remaining ?? 0 });

    return (
        <div
            role="alert"
            className={`flex shrink-0 items-center justify-center gap-2 border-b px-4 py-2 text-sm font-medium ${SEVERITY_STYLE[severity]}`}
        >
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{message}</span>
        </div>
    );
}
