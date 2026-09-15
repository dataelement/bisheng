/**
 * Pure rules behind the data tab (AC-56) — no React, no HTTP, so every one of
 * them is a plain unit test.
 *
 * The three that matter: how a cell is printed (a `null` must not read like
 * the word "null" typed by a user), how a typed string goes back to the scalar
 * the column stores (SQLite affinity rules, so `"12"` in an INTEGER column
 * becomes `12` and not the text `"12"`), and which columns a save actually
 * sends (only the ones that changed — the backend audits before / after per
 * submitted column, and re-sending an untouched value would log a no-op edit).
 */
import type {
  HostedAppCellValue,
  HostedAppColumn,
  HostedAppTableSchema,
} from "@/controllers/API/hostedAppData"

/** Page size the tab asks for; the backend caps at 200. */
export const DATA_PAGE_SIZE = 50

/** Widths for the resizable grid: the key column is narrow, the rest even. */
export const KEY_COLUMN_WIDTH = { defaultWidth: 110, minWidth: 80 }
export const VALUE_COLUMN_WIDTH = { defaultWidth: 180, minWidth: 100 }

export type CellAffinity = "integer" | "real" | "numeric" | "text"

/**
 * SQLite's declared-type affinity rules (§3.1 of the datatype doc), in the
 * order the engine applies them: INT wins over everything, then CHAR / CLOB /
 * TEXT, then BLOB (which we never edit), then REAL / FLOA / DOUB, else NUMERIC.
 */
export function columnAffinity(declaredType: string | null | undefined): CellAffinity {
  const type = (declaredType || "").toUpperCase()
  if (!type) return "text"
  if (type.includes("INT")) return "integer"
  if (type.includes("CHAR") || type.includes("CLOB") || type.includes("TEXT")) return "text"
  if (type.includes("BLOB")) return "text"
  if (type.includes("REAL") || type.includes("FLOA") || type.includes("DOUB")) return "real"
  return "numeric"
}

/** What goes in the grid cell. Distinguishes `null` from an empty string. */
export function formatCell(value: HostedAppCellValue | undefined): string {
  if (value === null || value === undefined) return ""
  if (typeof value === "boolean") return value ? "true" : "false"
  return String(value)
}

/** Whether the grid should draw the "empty" marker instead of text. */
export function isNullCell(value: HostedAppCellValue | undefined): boolean {
  return value === null || value === undefined
}

/** The text a cell shows in the edit input. `null` edits as an empty box. */
export function toInputText(value: HostedAppCellValue | undefined): string {
  return formatCell(value)
}

/**
 * Typed text → the scalar the column stores.
 *
 * Numbers are only produced where the column's affinity asks for one *and*
 * the text is a complete number; anything else stays a string and SQLite's
 * own affinity decides on write. An integer column given `"1.5"` therefore
 * sends the text — the manager will either store `1.5` (NUMERIC affinity
 * keeps it) or refuse, which is the honest outcome, not a silent truncation.
 */
export function coerceInput(text: string, column: Pick<HostedAppColumn, "type">): HostedAppCellValue {
  const affinity = columnAffinity(column.type)
  if (affinity === "text") return text
  const trimmed = text.trim()
  if (trimmed === "" || !/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(trimmed)) return text
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) return text
  if (affinity === "integer" && !Number.isInteger(parsed)) return text
  if (!Number.isSafeInteger(parsed) && Number.isInteger(parsed)) return text
  return parsed
}

/** Columns the dialog offers for editing: not the key, not binary. */
export function editableColumns(schema: HostedAppTableSchema): HostedAppColumn[] {
  if (!schema.editable) return []
  return schema.columns.filter((column) => column.editable && column.name !== schema.key.column)
}

export interface CellDraft {
  /** Text in the input; ignored while `setNull` is on. */
  text: string
  /** Explicit NULL — an empty input alone is an empty string, not NULL. */
  setNull: boolean
}

export function draftFromRow(
  columns: HostedAppColumn[],
  values: Record<string, HostedAppCellValue>,
): Record<string, CellDraft> {
  const draft: Record<string, CellDraft> = {}
  for (const column of columns) {
    const value = values[column.name]
    draft[column.name] = { text: toInputText(value), setNull: isNullCell(value) }
  }
  return draft
}

/**
 * The patch to send: only columns whose value actually differs from the row.
 *
 * Comparison is on the coerced scalar, so retyping `12` into an INTEGER cell
 * that already holds `12` is not a change, while typing `12` into a TEXT cell
 * that holds the number `12` (SQLite allows it) is — the stored type would
 * change, and the owner asked for it.
 */
export function buildRowPatch(
  columns: HostedAppColumn[],
  original: Record<string, HostedAppCellValue>,
  draft: Record<string, CellDraft>,
): Record<string, HostedAppCellValue> {
  const patch: Record<string, HostedAppCellValue> = {}
  for (const column of columns) {
    const cell = draft[column.name]
    if (!cell) continue
    const next: HostedAppCellValue = cell.setNull ? null : coerceInput(cell.text, column)
    const previous = original[column.name] ?? null
    if (next === previous) continue
    patch[column.name] = next
  }
  return patch
}

/**
 * Next `order` after clicking a header: none → ascending → descending → none.
 * The row key is appended server-side as tiebreaker, so this never has to.
 */
export function toggleOrder(current: string, column: string): string {
  if (current === column) return `-${column}`
  if (current === `-${column}`) return ""
  return column
}

export function orderDirection(current: string, column: string): "asc" | "desc" | null {
  if (current === column) return "asc"
  if (current === `-${column}`) return "desc"
  return null
}

/** File name the browser saves an export under. */
export function exportFileName(appName: string, table: string): string {
  const stem = (appName || "app").replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "") || "app"
  return `${stem}-${table}.csv`
}

/**
 * Hand a blob to the browser as a download. The same anchor trick
 * `util/utils.ts#downloadFile` uses, minus its unwrapped axios call: the bytes
 * here already came through the wrapped request module (constitution C7).
 */
export function saveBlob(blob: Blob, fileName: string): void {
  const link = document.createElement("a")
  link.href = URL.createObjectURL(blob)
  link.download = fileName
  link.click()
  URL.revokeObjectURL(link.href)
}
