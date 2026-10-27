import { Alert } from "@bisheng/ui";

import { locationContext } from "@/contexts/locationContext";
import {
    getCommercialLicenseStatus,
    getLicenseStatus,
    reportGatewayLicense,
    type CommercialLicenseItem,
} from "@/controllers/API/license";
import { useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { buildLicenseBannerCopy } from "./licenseBannerCopy";
import { shouldFetchGatewayLicenseStatus } from "./licenseBannerGateway";

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
        // Alert brings its own 8px margin and 12px radius, so the strip adds no
        // padding of its own. `flex` keeps those margins inside the measured
        // box — collapsed through a plain block they would leave
        // `--license-banner-h` 16px short of what the strip actually occupies.
        <div ref={ref} className="flex shrink-0 flex-col bg-background-main">
            <Alert live type="warning" description={message} />
        </div>
    );
}
