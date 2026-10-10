/** @jest-environment node */

import {
  resolveGuestAccessState,
  PUBLIC_APP_OFFLINE,
  PUBLIC_GUEST_CLOSED,
  PUBLIC_LINK_INVALID,
} from './guestAccessError';

const axiosError = (status: number, statusCode?: number) => ({
  response: { status, data: statusCode == null ? {} : { status_code: statusCode } },
});

describe('resolveGuestAccessState', () => {
  it('reads the business code out of a rejected response', () => {
    expect(resolveGuestAccessState(axiosError(404, PUBLIC_APP_OFFLINE))).toBe('offline');
    expect(resolveGuestAccessState(axiosError(404, PUBLIC_LINK_INVALID))).toBe('invalid');
    expect(resolveGuestAccessState(axiosError(403, PUBLIC_GUEST_CLOSED))).toBe('closed');
  });

  it('falls back to the bare status when no business code is present', () => {
    expect(resolveGuestAccessState(axiosError(404))).toBe('invalid');
    expect(resolveGuestAccessState(axiosError(403))).toBe('ok');
  });

  it('reads a denial carried inside a 200 envelope', () => {
    expect(resolveGuestAccessState({ status_code: PUBLIC_APP_OFFLINE })).toBe('offline');
  });

  it.each([
    ['a network error', new Error('Network Error')],
    ['nothing at all', undefined],
    ['a null', null],
    ['a server fault', axiosError(502)],
    ['a rate limit', axiosError(429)],
    ['a plain string', 'boom'],
  ])('does not block the page for %s', (_label, input) => {
    // A share page must not turn a transient failure into a dead end.
    expect(resolveGuestAccessState(input)).toBe('ok');
  });
});
