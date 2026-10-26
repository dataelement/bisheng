/**
 * Shared layout pieces of the publish tab.
 *
 * Every block on the tab is drawn from these so the page has exactly one
 * type ladder: panel title 14/medium, body 14/regular, field label and hint
 * 12/muted. Before they existed each card picked its own sizes and colours,
 * and the tab read as a pile of unrelated boxes.
 */

interface PanelProps {
  title: string
  /** One-line explanation under the title; keep it to a single sentence. */
  description?: React.ReactNode
  /** Controls aligned to the title row (right side). */
  actions?: React.ReactNode
  /** `danger` tints the border and title — only for the delete section. */
  tone?: "default" | "danger"
  className?: string
  children?: React.ReactNode
  "data-testid"?: string
}

export function Panel({
  title,
  description,
  actions,
  tone = "default",
  className = "",
  children,
  "data-testid": testId,
}: PanelProps) {
  const danger = tone === "danger"
  return (
    <section
      data-testid={testId}
      className={`rounded-md border bg-background-login p-5 ${
        danger ? "border-red-200 dark:border-red-900" : ""
      } ${className}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2
            className={`text-sm font-medium ${
              danger ? "text-red-600 dark:text-red-400" : ""
            }`}
          >
            {title}
          </h2>
          {description && (
            <p className="mt-1 text-xs text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </header>
      {children && <div className="mt-4">{children}</div>}
    </section>
  )
}

interface SubSectionProps {
  label: string
  actions?: React.ReactNode
  children: React.ReactNode
  "data-testid"?: string
}

/**
 * One topic inside a panel that groups several (the settings panel). Siblings
 * are separated by a rule; the label uses the field-label style so a sub-topic
 * never competes with the panel title.
 */
export function SubSection({
  label,
  actions,
  children,
  "data-testid": testId,
}: SubSectionProps) {
  return (
    <div
      data-testid={testId}
      className="flex flex-col gap-2 border-t pt-4 first:border-t-0 first:pt-0"
    >
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs text-muted-foreground">{label}</h3>
        {actions}
      </div>
      {children}
    </div>
  )
}

interface FieldProps {
  label: string
  children: React.ReactNode
}

/** One label/value pair; place inside a `<dl>`. */
export function Field({ label, children }: FieldProps) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-all text-sm">{children}</dd>
    </div>
  )
}

interface StatusTagProps {
  /** Colour classes, e.g. from `stateBadgeClass`. */
  className: string
  children: React.ReactNode
}

/** The one tag shape used for states on this tab. */
export function StatusTag({ className, children }: StatusTagProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-xs ${className}`}
    >
      {children}
    </span>
  )
}

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
