import { formatErrorTime } from "@bisheng/ui";
import { useEffect, useState } from "react";
import { Button } from "~/components/ui/Button";
import { SystemMaintenanceIllustration } from "~/components/illustrations";
import { useLocalize } from "~/hooks";

/**
 * Window event that surfaces the full-screen maintenance overlay. The axios
 * response interceptor (`~/api/request.ts`) dispatches it on any gateway/backend
 * HTTP 500 (service exception); keep the two string literals in sync.
 */
export const SERVICE_MAINTENANCE_EVENT = "bs:service-maintenance";

/**
 * Full-screen "system under maintenance" overlay shown when the backend service
 * is down (gateway returns HTTP 500). Mounted once at the app root; it stays
 * hidden until a 500 fires the event, then covers the app until a reload.
 */
export function SystemMaintenanceOverlay() {
    const localize = useLocalize();
    // When the first failure surfaced, written as on the crash page, so a
    // screenshot can be matched against backend logs. Later 500s keep the first.
    const [occurredAt, setOccurredAt] = useState<string | null>(null);
    const visible = occurredAt !== null;

    useEffect(() => {
        const show = () => setOccurredAt((prev) => prev ?? formatErrorTime(new Date()));
        window.addEventListener(SERVICE_MAINTENANCE_EVENT, show);
        return () => window.removeEventListener(SERVICE_MAINTENANCE_EVENT, show);
    }, []);

    if (!visible) return null;

    return (
        <div className="fixed inset-0 z-[2000] flex flex-col items-center justify-center gap-4 bg-white px-8 text-center">
            <SystemMaintenanceIllustration className="h-[120px] w-[120px]" />
            <div className="flex flex-col items-center gap-1">
                <p className="text-base font-medium leading-6 text-text-1">
                    {localize("com_app.service_maintenance_title")}
                </p>
                <p className="text-sm leading-[22px] text-text-3">
                    {localize("com_app.service_maintenance")}
                </p>
            </div>
            {/* Below the description, above refresh; same label and value as the crash page. */}
            <p className="flex items-center gap-2 text-sm leading-[22px]">
                <span className="font-medium text-text-1/80">{localize("com_error_page.time")}</span>
                <span className="select-text font-mono text-text-3">{occurredAt}</span>
            </p>
            <Button variant="outline" className="h-8 rounded-md px-4" onClick={() => window.location.reload()}>
                {localize("com_app.refresh")}
            </Button>
        </div>
    );
}
