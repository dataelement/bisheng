import { useCallback, useState } from "react";
import ChannelSquare from "~/pages/ChannelSquare";
import { ChannelPreviewDrawer } from "./ChannelPreviewDrawer";

/**
 * 频道广场 as a self-contained pane — the square list plus the preview drawer a card opens;
 * subscribing in the drawer refreshes the list — for hosts that are not the 频道 page (the
 * unified 广场). The 频道 page keeps its own wiring: there the drawer is also opened by share
 * links (`/channel/share/:id`) and the square by `?square=1`.
 */
export function ChannelSquarePane() {
    const [previewChannelId, setPreviewChannelId] = useState<string>();
    const [previewOpen, setPreviewOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);

    // Stable identities: ChannelSquare reloads its list when these change.
    const handlePreview = useCallback((id: string) => {
        setPreviewChannelId(id);
        setPreviewOpen(true);
    }, []);
    const handleSubscriptionChanged = useCallback(() => setRefreshKey((key) => key + 1), []);

    return (
        <>
            <ChannelSquare refreshKey={refreshKey} onPreviewChannel={handlePreview} isH5={false} />
            <ChannelPreviewDrawer
                channelId={previewChannelId}
                open={previewOpen}
                onOpenChange={(open) => {
                    setPreviewOpen(open);
                    if (!open) setPreviewChannelId(undefined);
                }}
                onSubscriptionChanged={handleSubscriptionChanged}
            />
        </>
    );
}
