import {
    getCommercialLicenseStatus,
    getLicenseStatus,
    reportGatewayLicense,
    type CommercialLicenseItem,
} from "@/controllers/API/license";
import i18next from "i18next";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { buildLicenseBannerCopy } from "./licenseBannerCopy";
import { shouldFetchGatewayLicenseStatus } from "./licenseBannerGateway";

// Sampled from the design PNG (not the warning token #FF7D00 / #FFF7E8):
// border+accent #E69739, fill #FFF8E6, body text #7A4B19.
const BANNER_CARD =
    "relative flex items-center justify-center gap-2 overflow-visible rounded-t-2xl rounded-b-none border-2 border-[#E69739] bg-[#FFF8E6] px-4 py-2.5 text-center text-sm text-[#7A4B19] dark:border-[#FF9626] dark:bg-[#4D1B00] dark:text-amber-100";
const BANNER_LABEL =
    "absolute -top-2.5 right-8 z-10 rounded-full border-2 border-[#E69739] bg-[#FFF8E6] px-2.5 py-[3px] text-xs font-medium leading-none text-[#E69739] dark:border-[#FF9626] dark:bg-[#4D1B00] dark:text-[#FF9626]";

/**
 * Persistent top banner for commercial license expiry.
 *
 * Caller (MainLayout) gates this to platform super admins. On mount it reads
 * the aggregated platform status first; Gateway `/api/license/status` is only
 * called when `gateway.checked_at` is missing or older than one day. After a
 * successful report it re-reads aggregation. Only expiring / expired rows
 * render. Height is published as `--license-banner-h`.
 */
export function LicenseBanner() {
    const { t } = useTranslation();
    const [licenses, setLicenses] = useState<CommercialLicenseItem[]>([]);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        let active = true;
        const load = async () => {
            // Public locale JSON is not in the Vite module graph; HMR of this
            // component would otherwise keep a stale `bs` bundle and fall back
            // to en-US ("License expiry Banner") while the body stays Chinese.
            await i18next.reloadResources(i18next.language, "bs");
            let aggregated = await getCommercialLicenseStatus();
            if (shouldFetchGatewayLicenseStatus(aggregated?.licenses)) {
                const gateway = await getLicenseStatus();
                if (gateway) {
                    await reportGatewayLicense(gateway);
                    aggregated = await getCommercialLicenseStatus();
                }
            }
            if (active) {
                setLicenses(aggregated?.licenses ?? []);
            }
        };
        void load();
        return () => {
            active = false;
        };
    }, []);

    const message = buildLicenseBannerCopy(licenses, t);
    const visible = Boolean(message);

    useLayoutEffect(() => {
        const root = document.documentElement;
        if (visible && ref.current) {
            root.style.setProperty("--license-banner-h", `${ref.current.offsetHeight}px`);
        } else {
            root.style.setProperty("--license-banner-h", "0px");
        }
        return () => root.style.setProperty("--license-banner-h", "0px");
    }, [visible, message]);

    if (!visible) return null;

    return (
        <div ref={ref} className="shrink-0 overflow-visible bg-background-main px-4 pt-5">
            <div role="alert" className={BANNER_CARD}>
                <span className={BANNER_LABEL}>{t("license.bannerLabel")}</span>
                <span
                    aria-hidden="true"
                    className="flex size-5 shrink-0 items-center justify-center rounded bg-[#E69739] text-[12px] font-semibold leading-none text-white dark:bg-[#FF9626]"
                >
                    !
                </span>
                <span>{message}</span>
            </div>
        </div>
    );
}
