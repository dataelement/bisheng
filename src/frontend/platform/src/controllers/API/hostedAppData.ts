/**
 * F054 hosted applications — the data plane (AC-56): the application's own
 * database, owner only. Split out of `hostedApp.ts` so that file stays under
 * the 600-line ceiling; the business codes (`HOSTED_APP_ERROR.DATA_*`) and the
 * envelope helpers live there and are what a caller branches on.
 *
 * The database never leaves the runtime host: every call here is one backend
 * endpoint that forwards to the runtime manager, and the platform never sees a
 * file path. There is no endpoint that carries SQL — the vocabulary is table
 * list, table shape, keyed rows, one-row update, CSV export — so there is no
 * DDL to refuse on this side either.
 *
 * Owner only: a tenant administrator is refused with 16162 exactly like a
 * stranger. Every read is `silent` for the same reason as the logs tab — the
 * refusal must render inline, not send the SPA to `/403`.
 */
import axios from "@/controllers/request"
import { APPS_BASE } from "./hostedApp"

/** A scalar cell as the manager serialises it; BLOBs arrive as placeholder text. */
export type HostedAppCellValue = string | number | boolean | null

export interface HostedAppTable {
  name: string
  column_count: number
}

export interface HostedAppColumn {
  name: string
  /** Declared SQLite type, possibly empty. */
  type: string
  notnull: boolean
  default: HostedAppCellValue
  /** Position in the primary key (0 = not part of it). */
  pk: number
  /** `false` for binary columns — shown as a placeholder, never edited. */
  editable: boolean
}

export interface HostedAppTableSchema {
  table: string
  columns: HostedAppColumn[]
  /** The column a row is addressed by on PATCH. `rowid` when there is no single-column primary key. */
  key: { column: string; kind: "rowid" | "primary_key" }
  /** `false` for a `WITHOUT ROWID` table with a composite key — readable, exportable, not editable. */
  editable: boolean
}

export interface HostedAppRow {
  /** Address for PATCH; `null` when the table is not editable. */
  key: HostedAppCellValue
  values: Record<string, HostedAppCellValue>
}

export interface HostedAppRowPage {
  rows: HostedAppRow[]
  total: number
  page: number
  size: number
  /** The order actually applied — `column`, `-column` or empty. */
  order: string
}

export interface HostedAppRowQuery {
  page?: number
  /** 1–200, backend default 50. */
  size?: number
  /** `column` or `-column`; the row key is always the tiebreaker. */
  order?: string
}

export interface HostedAppRowUpdateResult {
  table: string
  key: HostedAppCellValue
  before: Record<string, HostedAppCellValue>
  after: Record<string, HostedAppCellValue>
}

export async function getHostedAppTablesApi(
  appId: string,
): Promise<{ tables: HostedAppTable[] }> {
  return await axios.get(`${APPS_BASE}/${appId}/data/tables`, { silent: true })
}

export async function getHostedAppTableSchemaApi(
  appId: string,
  table: string,
): Promise<HostedAppTableSchema> {
  return await axios.get(
    `${APPS_BASE}/${appId}/data/tables/${encodeURIComponent(table)}/schema`,
    { silent: true },
  )
}

export async function getHostedAppTableRowsApi(
  appId: string,
  table: string,
  query: HostedAppRowQuery = {},
): Promise<HostedAppRowPage> {
  const params = new URLSearchParams()
  if (query.page !== undefined) params.set("page", String(query.page))
  if (query.size !== undefined) params.set("size", String(query.size))
  if (query.order) params.set("order", query.order)
  const qs = params.toString()
  return await axios.get(
    `${APPS_BASE}/${appId}/data/tables/${encodeURIComponent(table)}/rows${qs ? `?${qs}` : ""}`,
    { silent: true },
  )
}

/**
 * Change exactly one row. Only the columns in `values` are touched; the key
 * column is refused by the backend. Audited server-side as `app.data_row_edit`.
 *
 * `silent` so the dialog can tell 16165 ("the row moved under you") from a
 * generic failure and say so instead of toasting a bare message.
 */
export async function updateHostedAppRowApi(
  appId: string,
  table: string,
  key: HostedAppCellValue,
  values: Record<string, HostedAppCellValue>,
): Promise<HostedAppRowUpdateResult> {
  return await axios.patch(
    `${APPS_BASE}/${appId}/data/tables/${encodeURIComponent(table)}/rows/${encodeURIComponent(String(key))}`,
    { values },
    { silent: true },
  )
}

/**
 * The whole table as CSV bytes.
 *
 * The response is requested as a blob, and the interceptor hands a blob back
 * untouched — which means a *refusal* also arrives as a blob, because the
 * business-error envelope is still JSON. Saving that as `.csv` would give the
 * user a file containing `{"status_code": 16162, …}`, so a JSON-typed blob is
 * decoded and rejected as the envelope it is.
 */
export async function exportHostedAppTableApi(
  appId: string,
  table: string,
): Promise<Blob> {
  const blob: Blob = await axios.get(
    `${APPS_BASE}/${appId}/data/export?table=${encodeURIComponent(table)}`,
    { silent: true, responseType: "blob" },
  )
  if (blob && typeof blob.type === "string" && blob.type.includes("json")) {
    const text = await blob.text()
    let envelope: unknown = text
    try {
      envelope = JSON.parse(text)
    } catch {
      // Not an envelope after all; reject with the raw text below.
    }
    throw envelope
  }
  return blob
}

