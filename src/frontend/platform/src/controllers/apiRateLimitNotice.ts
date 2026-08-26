export const API_RATE_LIMIT_CODE = 10042
export const OPENFGA_OVERLOAD_CODE = 10046
export const API_RATE_LIMIT_DEDUPE_MS = 1500

const lastShownAt = new Map<string, number>()

export function shouldShowApiRateLimitNotice(
  code: number,
  message: string,
  now = Date.now()
): boolean {
  const key = `${code}:${message.trim()}`
  const previous = lastShownAt.get(key)
  if (previous !== undefined && now - previous < API_RATE_LIMIT_DEDUPE_MS) {
    return false
  }
  lastShownAt.set(key, now)
  return true
}

export function resetApiRateLimitNoticeDedupe(): void {
  lastShownAt.clear()
}

// OpenFGA overload shedding reuses this notice path: same "server is busy, come
// back shortly" shape as rate limiting, and the same dedupe keeps a burst of
// rejected requests from stacking toasts on top of each other.
export function isServerBusyCode(code: unknown): boolean {
  return code === API_RATE_LIMIT_CODE || code === OPENFGA_OVERLOAD_CODE
}
