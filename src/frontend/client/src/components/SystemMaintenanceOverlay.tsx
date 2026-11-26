import { Button, formatErrorTime, StateView, SystemMaintenanceIllustration } from "@bisheng/ui";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { checkServiceAvailability, SERVICE_MAINTENANCE_EVENT } from "~/api/request";
import { useLocalize } from "~/hooks";

interface SystemMaintenanceOverlayProps {
    children: ReactNode;
}

export function SystemMaintenanceOverlay({ children }: SystemMaintenanceOverlayProps) {
    const localize = useLocalize();
    const [occurredAt, setOccurredAt] = useState<Date | null>(null);
    const [isRetrying, setIsRetrying] = useState(false);
    const titleRef = useRef<HTMLSpanElement>(null);
    const visible = occurredAt !== null;

    useEffect(() => {
        const show = () => {
            const now = new Date();
            setOccurredAt((prev) => prev ?? now);
        };
        window.addEventListener(SERVICE_MAINTENANCE_EVENT, show);
        return () => window.removeEventListener(SERVICE_MAINTENANCE_EVENT, show);
    }, []);

    useEffect(() => {
        if (visible) titleRef.current?.focus();
    }, [visible]);

    const handleRetry = async () => {
        if (isRetrying) return;
        setIsRetrying(true);
        if (await checkServiceAvailability()) {
            window.location.reload();
            return;
        }
        setIsRetrying(false);
    };

    if (!occurredAt) return <>{children}</>;

    return (
        <main className="flex min-h-[100dvh] bg-bg-page">
            <StateView
                className="h-auto flex-1 py-6"
                image={<SystemMaintenanceIllustration />}
                title={(
                    <span ref={titleRef} role="heading" aria-level={1} tabIndex={-1} className="outline-none">
                        {localize("com_app.service_maintenance_title")}
                    </span>
                )}
                description={(
                    <>
                        {localize("com_app.service_maintenance")}
                        <span className="mt-1 block text-caption">
                            {localize("com_error_page.time")}{' '}
                            <time className="select-text" dateTime={occurredAt.toISOString()}>
                                {formatErrorTime(occurredAt)}
                            </time>
                        </span>
                    </>
                )}
                action={(
                    <Button type="button" loading={isRetrying} aria-disabled={isRetrying} onClick={handleRetry}>
                        {localize("com_ui_retry")}
                    </Button>
                )}
            />
        </main>
    );
}
