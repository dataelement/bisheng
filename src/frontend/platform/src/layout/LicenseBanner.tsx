import {
    getCommercialLicenseStatus,
    getLicenseStatus,
    reportGatewayLicense,
    type CommercialLicenseItem,
} from "@/controllers/API/license";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { buildLicenseBannerCopy } from "./licenseBannerCopy";
import { shouldFetchGatewayLicenseStatus } from "./licenseBannerGateway";

// Sampled from the design PNG (not the warning token #FF7D00 / #FFF7E8):
// border+accent #E69739, fill #FFF8E6, body text #7A4B19.
const BANNER_CARD =
    "flex items-center justify-center gap-2 rounded-t-2xl rounded-b-none border-2 border-[#E69739] bg-[#FFF8E6] px-4 py-2.5 text-center text-sm text-[#7A4B19] dark:border-[#FF9626] dark:bg-[#4D1B00] dark:text-amber-100";

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
    const { appConfig } = useContext(locationContext);
    const [licenses, setLicenses] = useState<CommercialLicenseItem[]>([]);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        let active = true;
        const load = async () => {
            let aggregated = await getCommercialLicenseStatus();
            if (shouldFetchGatewayLicenseStatus(aggregated?.licenses, Date.now(), appConfig.isPro)) {
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
    }, [appConfig.isPro]);

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
        <div ref={ref} className="shrink-0 bg-background-main px-4 pt-3">
            <div role="alert" className={BANNER_CARD}>
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
