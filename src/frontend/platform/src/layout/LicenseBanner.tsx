import { getLicenseStatus, LicenseStatus } from "@/controllers/API/license";
import { AlertTriangle } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

// Severity → styling. Only warning/critical/expired render a banner; normal/unknown render nothing.
// expired/critical share red; warning is amber. See feature 037.
const SEVERITY_STYLE: Record<string, string> = {
    warning: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
    critical: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
    expired: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
};

const VISIBLE_SEVERITIES = ["warning", "critical", "expired"];

// TODO(debug): TEMPORARY — force the banner visible so the license is not required
// to be expired while debugging the page-height offset. Revert to `false` before shipping.
const FORCE_DEBUG_VISIBLE = false;

/**
 * Persistent top banner that surfaces the gateway license expiry state.
 *
 * Caller (MainLayout) gates this to super admins; this component additionally renders nothing
 * unless the severity is warning/critical/expired (so normal/unknown/unavailable stay silent).
 * Status comes from the gateway via getLicenseStatus(); open-source deployments have no gateway,
 * so it resolves to null and the banner stays hidden.
 *
 * When visible it publishes its rendered height as the CSS custom property `--license-banner-h`
 * on :root, so viewport-based page heights (`calc(100vh - Npx)`) can subtract it. The property
 * defaults to `0px` whenever the banner is hidden, making that subtraction a no-op.
 */
export function LicenseBanner() {
    const { t } = useTranslation();
    const [status, setStatus] = useState<LicenseStatus | null>(null);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        let active = true;
        getLicenseStatus().then((res) => {
            if (active) setStatus(res);
        });
        return () => {
            active = false;
        };
    }, []);

    const realVisible = Boolean(status && VISIBLE_SEVERITIES.includes(status.severity));
    const visible = FORCE_DEBUG_VISIBLE || realVisible;

    // Publish / clear the banner height as a global CSS var for page-height calcs.
    useLayoutEffect(() => {
        const root = document.documentElement;
        if (visible && ref.current) {
            root.style.setProperty("--license-banner-h", `${ref.current.offsetHeight}px`);
        } else {
            root.style.setProperty("--license-banner-h", "0px");
        }
        return () => root.style.setProperty("--license-banner-h", "0px");
    }, [visible, status]);

    if (!visible) return null;

    const severity = realVisible ? status!.severity : "expired";
    const message = realVisible
        ? severity === "expired"
            ? t("license.expired")
            : t(`license.${severity}`, { days: status!.days_remaining ?? 0 })
        : t("license.expired"); // debug placeholder when the real license is not expired

    return (
        <div
            ref={ref}
            role="alert"
            className={`flex shrink-0 items-center justify-center gap-2 border-b px-4 py-2 text-sm font-medium ${SEVERITY_STYLE[severity]}`}
        >
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{message}</span>
        </div>
    );
}
