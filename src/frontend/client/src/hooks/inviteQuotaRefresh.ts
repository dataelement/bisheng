type Listener = () => void;

const listeners = new Set<Listener>();

/** Subscribe to invite-quota refreshes. Returns an unsubscribe function. */
export function subscribeInviteQuotaRefresh(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/**
 * Ask every mounted task-mode quota bar to reload remaining uses.
 * No-op when the invitation switch is off (nothing is subscribed).
 */
export function refreshInviteQuota(): void {
    listeners.forEach((listener) => {
        listener();
    });
}
