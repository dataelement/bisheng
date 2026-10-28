import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import {
  createInviteCodesApi,
  deleteInviteCodeApi,
  listInviteCodesApi,
  updateInviteCodeApi,
  type InviteCodeItem,
} from "@/controllers/API/inviteCode"
import { showApiError } from "@/controllers/request"
import { Button, Input, InputNumber, Pagination, SearchInput, Textarea, notification } from "@bisheng/ui"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

const PAGE_SIZE = 20

interface Draft {
  name: string
  num: number | null
  limit: number | null
}

const emptyDraft = (): Draft => ({ name: "", num: 10, limit: 10 })

/** System-admin invite-code list. The tab gate lives in SystemPage. */
export function InviteCodeTab() {
  const { t } = useTranslation()
  const [rows, setRows] = useState<InviteCodeItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [keyword, setKeyword] = useState("")
  const [applied, setApplied] = useState("")
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<InviteCodeItem | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft())
  const [created, setCreated] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listInviteCodesApi({ page, pageSize, keyword: applied })
      if (data) {
        setRows(data.items ?? [])
        setTotal(data.total ?? 0)
      }
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => {
    void load().catch(showApiError)
  }, [load])

  const applySearch = (value: string) => {
    setPage(1)
    setApplied(value.trim())
  }

  const openCreate = () => {
    setDraft(emptyDraft())
    setCreated([])
    setCreating(true)
  }

  const openEdit = (row: InviteCodeItem) => {
    setEditing(row)
    setDraft({ name: row.batch_name, num: null, limit: row.limit })
  }

  const notify = (description: string) => {
    notification.open({ type: "success", title: t("system.inviteCode.tab"), description })
  }

  const handleCreate = () => {
    const name = draft.name.trim()
    const num = draft.num
    const limit = draft.limit
    if (!name || name.length > 64 || num == null || num < 1 || num > 100 || limit == null || limit < 1 || limit > 100000) {
      notification.open({ type: "error", title: t("prompt"), description: t("system.inviteCode.feedback.invalid") })
      return
    }
    setBusy(true)
    void createInviteCodesApi(name, num, limit)
      .then((result) => {
        setCreated(result?.codes ?? [])
        notify(t("system.inviteCode.feedback.created"))
        void load()
      })
      .catch(showApiError)
      .finally(() => setBusy(false))
  }

  const handleSave = () => {
    if (!editing) return
    const name = draft.name.trim()
    const limit = draft.limit
    if (!name || name.length > 64 || limit == null || limit < 1 || limit > 100000 || limit < editing.used) {
      notification.open({
        type: "error",
        title: t("prompt"),
        description: t("system.inviteCode.editDialog.limitHint", { used: editing.used }),
      })
      return
    }
    setBusy(true)
    void updateInviteCodeApi(editing.id, name, limit)
      .then(() => {
        setEditing(null)
        notify(t("system.inviteCode.feedback.saved"))
        void load()
      })
      .catch(showApiError)
      .finally(() => setBusy(false))
  }

  const handleDelete = (row: InviteCodeItem) => {
    bsConfirm({
      title: t("system.inviteCode.deleteConfirm.title"),
      desc: t("system.inviteCode.deleteConfirm.desc", { code: row.code }),
      okTxt: t("system.inviteCode.actions.delete"),
      onOk: (close) => {
        close()
        void deleteInviteCodeApi(row.id)
          .then(() => {
            notify(t("system.inviteCode.feedback.deleted"))
            void load()
          })
          .catch(showApiError)
      },
    })
  }

  const handleCopy = () => {
    void navigator.clipboard.writeText(created.join("\n")).then(() => {
      notify(t("system.inviteCode.feedback.copied"))
    })
  }

  const pagerLocale = {
    total: (count: string) => t("system.inviteCode.pagination.total", { total: count }),
    pageSize: (size: number) => t("system.inviteCode.pagination.pageSize", { size }),
    jumpPrefix: t("system.inviteCode.pagination.jumpPrefix"),
    jumpSuffix: t("system.inviteCode.pagination.jumpSuffix"),
    jumpError: (totalPages: number) => t("system.inviteCode.pagination.jumpError", { totalPages }),
    prev: t("system.inviteCode.pagination.prev"),
    next: t("system.inviteCode.pagination.next"),
    nav: t("system.inviteCode.pagination.nav"),
  }

  return (
    <div className="flex h-full min-h-0 flex-col px-2 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <SearchInput
          className="w-72"
          value={keyword}
          placeholder={t("system.inviteCode.searchPlaceholder")}
          onChange={(event) => {
            const value = event.target.value
            setKeyword(value)
            if (!value.trim()) applySearch("")
          }}
          onSearch={applySearch}
        />
        <Button type="button" color="primary" variant="solid" onClick={openCreate}>
          {t("system.inviteCode.create")}
        </Button>
      </div>
      <p className="mb-3 text-caption text-text-3">{t("system.inviteCode.hint")}</p>
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && rows.length === 0 ? (
          <p className="py-8 text-center text-caption text-text-3">{t("system.inviteCode.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="py-8 text-center text-caption text-text-3">{t("system.inviteCode.empty")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("system.inviteCode.columns.code")}</TableHead>
                <TableHead>{t("system.inviteCode.columns.batch")}</TableHead>
                <TableHead>{t("system.inviteCode.columns.limit")}</TableHead>
                <TableHead>{t("system.inviteCode.columns.used")}</TableHead>
                <TableHead>{t("system.inviteCode.columns.remaining")}</TableHead>
                <TableHead>{t("system.inviteCode.columns.user")}</TableHead>
                <TableHead>{t("system.inviteCode.columns.created")}</TableHead>
                <TableHead className="text-right">{t("operations")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-mono">{row.code}</TableCell>
                  <TableCell>{row.batch_name}</TableCell>
                  <TableCell>{row.limit}</TableCell>
                  <TableCell>{row.used}</TableCell>
                  <TableCell>{row.limit - row.used}</TableCell>
                  <TableCell>{row.bind_user ? row.bind_user_name || row.bind_user : t("system.inviteCode.unbound")}</TableCell>
                  <TableCell>{row.create_time}</TableCell>
                  <TableCell className="text-right">
                    <Button type="button" color="primary" variant="text" size="small" onClick={() => openEdit(row)}>
                      {t("system.inviteCode.actions.edit")}
                    </Button>
                    <Button type="button" color="danger" variant="text" size="small" onClick={() => handleDelete(row)}>
                      {t("system.inviteCode.actions.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      <Pagination
        className="mt-3"
        total={total}
        current={page}
        pageSize={pageSize}
        showTotal
        showSizeChanger
        locale={pagerLocale}
        onChange={(nextPage, nextSize) => {
          setPage(nextPage)
          setPageSize(nextSize)
        }}
      />

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{t("system.inviteCode.createDialog.title")}</DialogTitle>
          </DialogHeader>
          {created.length > 0 ? (
            <div className="space-y-3">
              <p className="text-body text-text-2">{t("system.inviteCode.createDialog.result", { count: created.length })}</p>
              <Textarea readOnly rows={6} value={created.join("\n")} />
            </div>
          ) : (
            <div className="space-y-3">
              <label className="block text-caption text-text-2">
                {t("system.inviteCode.createDialog.name")}
                <Input
                  className="mt-1"
                  maxLength={64}
                  value={draft.name}
                  placeholder={t("system.inviteCode.createDialog.namePlaceholder")}
                  onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label className="block text-caption text-text-2">
                {t("system.inviteCode.createDialog.num")}
                <InputNumber
                  className="mt-1"
                  min={1}
                  max={100}
                  value={draft.num}
                  increaseLabel={t("system.inviteCode.actions.increase")}
                  decreaseLabel={t("system.inviteCode.actions.decrease")}
                  onChange={(value) => setDraft((current) => ({ ...current, num: value }))}
                />
              </label>
              <label className="block text-caption text-text-2">
                {t("system.inviteCode.createDialog.limit")}
                <InputNumber
                  className="mt-1"
                  min={1}
                  max={100000}
                  value={draft.limit}
                  increaseLabel={t("system.inviteCode.actions.increase")}
                  decreaseLabel={t("system.inviteCode.actions.decrease")}
                  onChange={(value) => setDraft((current) => ({ ...current, limit: value }))}
                />
              </label>
              <p className="text-caption text-text-3">{t("system.inviteCode.createDialog.rangeHint")}</p>
            </div>
          )}
          <DialogFooter>
            {created.length > 0 ? (
              <>
                <Button type="button" color="default" variant="outlined" onClick={handleCopy}>
                  {t("system.inviteCode.actions.copy")}
                </Button>
                <Button type="button" color="primary" variant="solid" onClick={() => setCreating(false)}>
                  {t("system.inviteCode.actions.done")}
                </Button>
              </>
            ) : (
              <>
                <Button type="button" color="default" variant="outlined" onClick={() => setCreating(false)}>
                  {t("system.inviteCode.actions.cancel")}
                </Button>
                <Button type="button" color="primary" variant="solid" disabled={busy} onClick={handleCreate}>
                  {t("system.inviteCode.createDialog.submit")}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editing !== null} onOpenChange={(open) => { if (!open) setEditing(null) }}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{t("system.inviteCode.editDialog.title")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block text-caption text-text-2">
              {t("system.inviteCode.editDialog.name")}
              <Input
                className="mt-1"
                maxLength={64}
                value={draft.name}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="block text-caption text-text-2">
              {t("system.inviteCode.editDialog.limit")}
              <InputNumber
                className="mt-1"
                min={editing?.used ?? 1}
                max={100000}
                value={draft.limit}
                increaseLabel={t("system.inviteCode.actions.increase")}
                decreaseLabel={t("system.inviteCode.actions.decrease")}
                onChange={(value) => setDraft((current) => ({ ...current, limit: value }))}
              />
            </label>
            <p className="text-caption text-text-3">
              {t("system.inviteCode.editDialog.limitHint", { used: editing?.used ?? 0 })}
            </p>
          </div>
          <DialogFooter>
            <Button type="button" color="default" variant="outlined" onClick={() => setEditing(null)}>
              {t("system.inviteCode.actions.cancel")}
            </Button>
            <Button type="button" color="primary" variant="solid" disabled={busy} onClick={handleSave}>
              {t("system.inviteCode.actions.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
