import { useEffect, useRef, useState } from "react";
import { useActivate, useUnactivate } from "react-activation";
import { type QueryClient, useQuery } from "@tanstack/react-query";
import { getChannelDetailApi } from "~/api/channels";

export const CHANNEL_STATE_REFRESH_MS = 30_000;
const CHANNEL_STATE_KEYS = new Set([
    "channels", "channelDetail", "channelPreviewDetail", "channelRecommend",
]);

export function refreshChannelState(queryClient: QueryClient) {
    return queryClient.invalidateQueries(
        { predicate: (query) => CHANNEL_STATE_KEYS.has(String(query.queryKey[0])) },
        { cancelRefetch: false },
    );
}

/** Revalidate while the visible channel surface is active, including KeepAlive restores. */
export function useChannelStateRefresh(refresh: () => void, enabled = true) {
    const refreshRef = useRef(refresh);
    refreshRef.current = refresh;
    const [active, setActive] = useState(true);
    useActivate(() => {
        setActive(true);
        if (enabled) refreshRef.current();
    });
    useUnactivate(() => setActive(false));
    useEffect(() => {
        if (!enabled || !active) return;
        const revalidate = () => {
            if (document.visibilityState === "visible") refreshRef.current();
        };
        window.addEventListener("focus", revalidate);
        document.addEventListener("visibilitychange", revalidate);
        const timer = window.setInterval(revalidate, CHANNEL_STATE_REFRESH_MS);
        return () => {
            window.clearInterval(timer);
            window.removeEventListener("focus", revalidate);
            document.removeEventListener("visibilitychange", revalidate);
        };
    }, [active, enabled]);
}

/** Close an opened content view as soon as its refreshed permission loses visibility. */
export function useChannelAccessGuard(channelId: string | undefined, onRevoked: () => void) {
    const onRevokedRef = useRef(onRevoked);
    onRevokedRef.current = onRevoked;
    const { data, isFetching } = useQuery({
        queryKey: ["channelDetail", channelId],
        queryFn: () => getChannelDetailApi(channelId!),
        enabled: Boolean(channelId),
        staleTime: 0,
    });
    useEffect(() => {
        if (channelId && !isFetching && Array.isArray(data?.actions) && !data.actions.includes("visible")) {
            onRevokedRef.current();
        }
    }, [channelId, data, isFetching]);
}
