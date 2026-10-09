/**
 * Turning a failed share-link lookup into something a visitor can read.
 *
 * A guest has no account, no home page and no support channel inside the
 * product, so the only useful distinction is between "the app was taken
 * offline" and "this link does not work". The backend says which via the
 * business code in the envelope; the HTTP status stays coarse on purpose.
 */

import { extractApiStatusCode } from '~/utils/apiStatusError';

export type GuestAccessState = 'loading' | 'ok' | 'offline' | 'invalid' | 'closed';

export const PUBLIC_LINK_INVALID = 26101;
export const PUBLIC_APP_OFFLINE = 26102;
export const PUBLIC_GUEST_CLOSED = 26103;

/**
 * Map a rejected response onto a visitor-facing state.
 *
 * Anything that is not a deliberate policy denial resolves to `ok` so the page
 * still renders: a share page must not turn a flaky network or a 5xx into a
 * dead end. Only the codes below — and a bare 404 an older backend would
 * return for a missing link — block the page. A bare 403 is not "guest
 * closed": downstream permission denials must stay in the conversation.
 */
export function resolveGuestAccessState(input: unknown): GuestAccessState {
  const code = extractApiStatusCode(input);
  if (code === null) return 'ok';

  switch (code) {
    case PUBLIC_APP_OFFLINE:
      return 'offline';
    case PUBLIC_LINK_INVALID:
    case 404:
      return 'invalid';
    case PUBLIC_GUEST_CLOSED:
      return 'closed';
    default:
      return 'ok';
  }
}
