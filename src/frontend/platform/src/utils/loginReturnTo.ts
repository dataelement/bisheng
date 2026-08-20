/**
 * Post-login "return to where you were" handoff.
 *
 * CROSS-APP CONTRACT — the client app writes these two keys on its way to the
 * login page (`src/frontend/client/src/utils/loginRedirect.ts`); the platform
 * app owns the login page, so it is the one that must consume them. Rename them
 * in both apps or not at all.
 */
const LOGIN_PATHNAME_KEY = 'LOGIN_PATHNAME';
const LOGIN_PATHNAME_AT_KEY = 'LOGIN_PATHNAME_AT';

/**
 * How long a stored return target stays honourable. Without this, a return
 * target left behind by an abandoned 401 hours ago would silently yank the user
 * out of the admin shell on their next login.
 */
const MAX_AGE_MS = 10 * 60 * 1000;

function clear(): void {
    try {
        localStorage.removeItem(LOGIN_PATHNAME_KEY);
        localStorage.removeItem(LOGIN_PATHNAME_AT_KEY);
    } catch {
        /* storage disabled — nothing to clear */
    }
}

/**
 * Read, validate and consume the stored return target. Returns null when there
 * is nothing valid to go back to.
 *
 * Always consumes (one-shot): a value that fails validation is dropped rather
 * than left to be re-evaluated on the next login.
 */
export function consumeLoginReturnTo(): string | null {
    let raw: string | null = null;
    let at: string | null = null;
    try {
        raw = localStorage.getItem(LOGIN_PATHNAME_KEY);
        at = localStorage.getItem(LOGIN_PATHNAME_AT_KEY);
    } catch {
        return null;
    }
    if (!raw) {
        clear();
        return null;
    }
    clear();

    // Missing timestamp is treated as fresh: values written by an older client
    // build carry no timestamp, and dropping them would regress the flow.
    if (at) {
        const stamp = Number(at);
        if (!Number.isFinite(stamp) || Date.now() - stamp > MAX_AGE_MS) {
            return null;
        }
    }

    // Same-origin only. The value is ours by construction, but honouring an
    // arbitrary absolute URL here would turn login into an open redirect.
    try {
        const target = new URL(raw, location.origin);
        if (target.origin !== location.origin) {
            return null;
        }
        return target.href;
    } catch {
        return null;
    }
}
