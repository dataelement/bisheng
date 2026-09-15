/**
 * Data tab (AC-56) — the application's own database: table list → one page
 * of rows → single-row edit → CSV export. No DDL: the structure the app
 * created is what is shown, and nothing here can change it.
 *
 * Owner only. A tenant administrator is refused with business code 16162
 * inside a 200 envelope, rendered as a notice in place — a real 403 on a GET
 * would make the platform interceptor navigate the whole SPA to `/403`, and
 * one forbidden tab must not cost the detail page. 16163 is not a failure
 * either: the app simply has not created its database yet, which is the
 * empty state.
 *
 * Reads go through `useState + useEffect` (react-query is lint-frozen in this
 * app). Ordering is server-side with the row key as tiebreaker, so paging
 * never repeats or skips a row.
 */
import { Button } from "@/components/bs-ui/button"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import {
  ColumnResizeHandle,
  useResizableColumns,
} from "@/components/bs-ui/table/useResizableColumns"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { cname } from "@/components/bs-ui/utils"
import {
  getHostedAppErrorCode,
  getHostedAppErrorMessage,
  HOSTED_APP_ERROR,
} from "@/controllers/API/hostedApp"
import {
  exportHostedAppTableApi,
  getHostedAppTableRowsApi,
  getHostedAppTableSchemaApi,
  getHostedAppTablesApi,
  type HostedAppRow,
  type HostedAppRowPage,
  type HostedAppTable,
  type HostedAppTableSchema,
} from "@/controllers/API/hostedAppData"
import { ArrowDown, ArrowUp, Download, Pencil, RefreshCw } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  DATA_PAGE_SIZE,
  exportFileName,
  formatCell,
  isNullCell,
  KEY_COLUMN_WIDTH,
  orderDirection,
  saveBlob,
  toggleOrder,
  VALUE_COLUMN_WIDTH,
} from "./data/dataTabModel"
import { RowEditDialog } from "./data/RowEditDialog"

interface DataTabProps {
  appId: string
  /** Used for the export file name only. */
  appName: string
}

type TableListState = "loading" | "ready" | "forbidden" | "not_ready" | "failed"

export function DataTab({ appId, appName }: DataTabProps) {
  const { t } = useTranslation()

  // -- table list ----------------------------------------------------------
  const [listState, setListState] = useState<TableListState>("loading")
  // The backend's own message, if it sent one; translated fallback at render
  // time. Loaders keep `t` out of their dependencies on purpose: a translator
  // that changes identity would otherwise re-fire the effect and re-enter
  // "loading" forever.
  const [listFailure, setListFailure] = useState("")
  const [tables, setTables] = useState<HostedAppTable[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  const loadTables = useCallback(() => {
    setListState("loading")
    getHostedAppTablesApi(appId)
      .then((data) => {
        const list = data?.tables || []
        setTables(list)
        setListState("ready")
        setListFailure("")
        setSelected((current) =>
          current && list.some((table) => table.name === current) ? current : list[0]?.name ?? null,
        )
      })
      .catch((error) => {
        setTables([])
        setSelected(null)
        const code = getHostedAppErrorCode(error)
        if (code === HOSTED_APP_ERROR.DATA_FORBIDDEN) {
          setListState("forbidden")
        } else if (code === HOSTED_APP_ERROR.DATA_NOT_READY) {
          setListState("not_ready")
        } else {
          setListState("failed")
          setListFailure(getHostedAppErrorMessage(error))
        }
      })
  }, [appId])

  useEffect(() => {
    loadTables()
  }, [loadTables])

  // -- one table -----------------------------------------------------------
  const [schema, setSchema] = useState<HostedAppTableSchema | null>(null)
  const [pageData, setPageData] = useState<HostedAppRowPage | null>(null)
  const [page, setPage] = useState(1)
  const [order, setOrder] = useState("")
  const [rowsLoading, setRowsLoading] = useState(false)
  /** `gone`: the table vanished under us; `failed`: anything else, with the backend's message. */
  const [rowsFailure, setRowsFailure] = useState<{ kind: "gone" } | { kind: "failed"; message: string } | null>(
    null,
  )
  const [editing, setEditing] = useState<HostedAppRow | null>(null)
  const [exporting, setExporting] = useState(false)

  // A new table starts at page 1 with no order; the previous table's cursor
  // means nothing here.
  useEffect(() => {
    setPage(1)
    setOrder("")
    setSchema(null)
    setPageData(null)
    setRowsFailure(null)
  }, [selected])

  const loadRows = useCallback(() => {
    if (!selected) return
    setRowsLoading(true)
    Promise.all([
      getHostedAppTableSchemaApi(appId, selected),
      getHostedAppTableRowsApi(appId, selected, {
        page,
        size: DATA_PAGE_SIZE,
        order: order || undefined,
      }),
    ])
      .then(([shape, rows]) => {
        setSchema(shape)
        setPageData(rows)
        setRowsFailure(null)
      })
      .catch((error) => {
        setPageData(null)
        const code = getHostedAppErrorCode(error)
        if (code === HOSTED_APP_ERROR.DATA_TABLE_NOT_FOUND) {
          // The app dropped the table since the list was read; the list is
          // the thing that is stale, so re-read it rather than complain.
          setRowsFailure({ kind: "gone" })
          loadTables()
        } else {
          setRowsFailure({ kind: "failed", message: getHostedAppErrorMessage(error) })
        }
      })
      .finally(() => setRowsLoading(false))
  }, [appId, selected, page, order, loadTables])

  useEffect(() => {
    loadRows()
  }, [loadRows])

  const columns = useMemo(() => schema?.columns ?? [], [schema])
  const canEdit = !!schema?.editable
  const columnDefs = useMemo(
    () => [
      KEY_COLUMN_WIDTH,
      ...columns.map(() => VALUE_COLUMN_WIDTH),
      // trailing action column; the resize handle is never drawn on it
      { defaultWidth: 90, minWidth: 70 },
    ],
    [columns],
  )
  const grid = useResizableColumns(columnDefs)
  const lastColumn = columnDefs.length - 1

  const handleSort = (column: string) => {
    setOrder((current) => toggleOrder(current, column))
    setPage(1)
  }

  const handleExport = async () => {
    if (!selected || exporting) return
    setExporting(true)
    try {
      const blob = await exportHostedAppTableApi(appId, selected)
      saveBlob(blob, exportFileName(appName, selected))
    } catch (error) {
      toast({
        variant: "error",
        description: getHostedAppErrorMessage(error) || t("hostedApp.data.exportFailed"),
      })
    } finally {
      setExporting(false)
    }
  }

  // -- states that replace the whole tab ----------------------------------
  if (listState === "loading") {
    return <Notice text={t("hostedApp.data.loading")} />
  }
  if (listState === "forbidden") {
    return <Notice text={t("hostedApp.data.forbidden")} />
  }
  if (listState === "not_ready") {
    return <Notice text={t("hostedApp.data.notReady")} />
  }
  if (listState === "failed") {
    return (
      <Notice
        text={listFailure || t("hostedApp.data.loadFailed")}
        retry={loadTables}
        retryLabel={t("hostedApp.data.refresh")}
      />
    )
  }
  if (tables.length === 0) {
    return <Notice text={t("hostedApp.data.noTables")} retry={loadTables} retryLabel={t("hostedApp.data.refresh")} />
  }

  return (
    <div className="flex h-full min-h-0 gap-4 pb-4">
      {/* table list */}
      <aside className="flex w-52 shrink-0 flex-col gap-1 overflow-y-auto rounded-md border p-2">
        <p className="px-2 py-1 text-xs text-muted-foreground">
          {t("hostedApp.data.tables", { count: tables.length })}
        </p>
        {tables.map((table) => (
          <button
            key={table.name}
            type="button"
            aria-pressed={table.name === selected}
            className={cname(
              "flex items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted",
              table.name === selected && "bg-muted font-medium",
            )}
            onClick={() => setSelected(table.name)}
          >
            <span className="truncate">{table.name}</span>
            <span className="ml-2 shrink-0 text-xs text-muted-foreground">
              {t("hostedApp.data.columnCount", { count: table.column_count })}
            </span>
          </button>
        ))}
      </aside>

      {/* rows */}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{selected}</span>
          {pageData && (
            <span className="text-xs text-muted-foreground">
              {t("hostedApp.data.rowCount", { count: pageData.total })}
            </span>
          )}
          {schema && !schema.editable && (
            <span className="rounded-sm bg-muted px-1 text-xs text-muted-foreground">
              {t("hostedApp.data.readOnlyTable")}
            </span>
          )}
          <div className="ml-auto flex gap-2">
            <Button variant="outline" size="sm" disabled={rowsLoading} onClick={loadRows}>
              <RefreshCw className={cname("mr-1 size-3.5", rowsLoading && "animate-spin")} />
              {t("hostedApp.data.refresh")}
            </Button>
            <Button variant="outline" size="sm" disabled={exporting || !selected} onClick={handleExport}>
              <Download className="mr-1 size-3.5" />
              {t("hostedApp.data.export")}
            </Button>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">{t("hostedApp.data.hint")}</p>

        <div className="min-h-0 flex-1 overflow-auto rounded-md border">
          {rowsFailure ? (
            <p className="p-4 text-sm text-muted-foreground">
              {rowsFailure.kind === "gone"
                ? t("hostedApp.data.tableGone")
                : rowsFailure.message || t("hostedApp.data.loadFailed")}
            </p>
          ) : !schema || !pageData ? (
            <p className="p-4 text-sm text-muted-foreground">{t("hostedApp.data.loading")}</p>
          ) : pageData.rows.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">{t("hostedApp.data.noRows")}</p>
          ) : (
            <Table noScroll style={{ tableLayout: "fixed", width: grid.totalWidth }}>
              <TableHeader>
                <TableRow>
                  <TableHead {...grid.getThProps(0)}>
                    <span className="truncate">{schema.key.column}</span>
                    <ColumnResizeHandle columnIndex={0} lastColumn={false} startResize={grid.startResize} />
                  </TableHead>
                  {columns.map((column, index) => {
                    const direction = orderDirection(order, column.name)
                    return (
                      <TableHead key={column.name} {...grid.getThProps(index + 1)}>
                        <button
                          type="button"
                          className="flex max-w-full items-center gap-1 truncate"
                          title={column.type || undefined}
                          onClick={() => handleSort(column.name)}
                        >
                          <span className="truncate">{column.name}</span>
                          {direction === "asc" && <ArrowUp className="size-3 shrink-0" />}
                          {direction === "desc" && <ArrowDown className="size-3 shrink-0" />}
                        </button>
                        <ColumnResizeHandle
                          columnIndex={index + 1}
                          lastColumn={index + 1 === lastColumn}
                          startResize={grid.startResize}
                        />
                      </TableHead>
                    )
                  })}
                  <TableHead {...grid.getThProps(lastColumn)} className="text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageData.rows.map((row, rowIndex) => (
                  <TableRow key={`${formatCell(row.key)}-${rowIndex}`}>
                    <TableCell {...grid.getTdProps(0)} className="truncate font-mono text-xs">
                      {formatCell(row.key)}
                    </TableCell>
                    {columns.map((column, index) => {
                      const value = row.values[column.name]
                      return (
                        <TableCell
                          key={column.name}
                          {...grid.getTdProps(index + 1)}
                          className="truncate"
                          title={formatCell(value)}
                        >
                          {isNullCell(value) ? (
                            <span className="text-xs text-muted-foreground">{t("hostedApp.data.nullLabel")}</span>
                          ) : (
                            formatCell(value)
                          )}
                        </TableCell>
                      )
                    })}
                    <TableCell {...grid.getTdProps(lastColumn)} className="text-right">
                      {canEdit && !isNullCell(row.key) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={t("hostedApp.data.edit")}
                          onClick={() => setEditing(row)}
                        >
                          <Pencil className="size-3.5" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        {pageData && pageData.total > DATA_PAGE_SIZE && (
          <AutoPagination
            page={page}
            pageSize={DATA_PAGE_SIZE}
            total={pageData.total}
            onChange={(next) => setPage(next)}
          />
        )}
      </section>

      {schema && (
        <RowEditDialog
          appId={appId}
          schema={schema}
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={loadRows}
        />
      )}
    </div>
  )
}

interface NoticeProps {
  text: string
  retry?: () => void
  retryLabel?: string
}

function Notice({ text, retry, retryLabel }: NoticeProps) {
  return (
    <div className="flex h-40 flex-col items-center justify-center gap-3 rounded-md border bg-background-login">
      <p className="text-sm text-muted-foreground">{text}</p>
      {retry && (
        <Button variant="outline" size="sm" onClick={retry}>
          {retryLabel}
        </Button>
      )}
    </div>
  )
}
