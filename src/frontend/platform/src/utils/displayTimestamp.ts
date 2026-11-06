/**
 * Wire timestamp → `YYYY-MM-DD HH:mm:ss` for display.
 *
 * A value carrying a zone (`Z` / `+08:00`, e.g. the container's `started_at`)
 * is converted to the viewer's local time. A naive value is shown as sent:
 * guessing its zone would hide a backend inconsistency instead of exposing it.
 * Fractional seconds are dropped either way — nobody reads nanoseconds.
 */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "-"
  const zoned = /(Z|[+-]\d{2}:?\d{2})$/.test(value)
  if (zoned) {
    // Container runtimes send nanoseconds; Date only reliably parses up to ms.
    const parsed = new Date(value.replace(/(\.\d{3})\d+/, "$1"))
    if (!Number.isNaN(parsed.getTime())) {
      const pad = (n: number) => String(n).padStart(2, "0")
      return (
        `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ` +
        `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`
      )
    }
  }
  const match = value.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/)
  return match ? `${match[1]} ${match[2]}` : value
}
