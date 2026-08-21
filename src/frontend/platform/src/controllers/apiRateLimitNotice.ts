export const API_RATE_LIMIT_CODE = 10042
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
