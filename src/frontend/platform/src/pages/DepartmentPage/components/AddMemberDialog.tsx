// @ts-strict-ignore
import { useSubjectSearch } from "@/components/bs-comp/selectComponent/useSubjectSearch"
import { SubjectBusinessId, SubjectSearchStatus } from "@/components/bs-comp/selectComponent/SubjectSearchStatus"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Label } from "@/components/bs-ui/label"
import { SearchInput } from "@/components/bs-ui/input"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { addDepartmentMembersApi } from "@/controllers/API/department"
import { getUsersApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { useCallback, useState } from "react"
import { useTranslation } from "react-i18next"

interface AddMemberDialogProps {
  deptId: string
  onAdded: () => void
  onClose: () => void
}

interface UserItem {
  user_id: number
  user_name: string
  external_id?: string | null
}

export function AddMemberDialog({ deptId, onAdded, onClose }: AddMemberDialogProps) {
  const { t } = useTranslation()
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [isPrimary, setIsPrimary] = useState(1)
  const [loading, setLoading] = useState(false)

  const search = useSubjectSearch<UserItem>({
    emptyByDefault: true,
    fetchPage: (keyword, page, signal) => getUsersApi({ page, pageSize: 10, name: keyword }, { signal }),
  })
  const users = search.rows
  const keyword = search.keyword

  const toggleUser = useCallback((userId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(userId)) next.delete(userId)
      else next.add(userId)
      return next
    })
  }, [])

  const handleSubmit = useCallback(() => {
    if (selectedIds.size === 0) {
      toast({ title: t("bs:department.selectMembers"), variant: "error" })
      return
    }
    setLoading(true)
    captureAndAlertRequestErrorHoc(
      addDepartmentMembersApi(deptId, {
        user_ids: Array.from(selectedIds),
        is_primary: isPrimary,
      })
    ).then((res) => {
      setLoading(false)
      if (res !== null) {
        toast({ title: t("bs:department.addMember"), variant: "success" })
        onAdded()
      }
    })
  }, [deptId, selectedIds, isPrimary, onAdded, t])

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("bs:department.addMember")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {/* Search */}
          <div className="space-y-2">
            <Label>{t("bs:department.searchMember")}</Label>
            <SearchInput
              placeholder={t("bs:subjectSearch.userPlaceholder")}
              {...search.inputProps}
            />
          </div>

          {/* User list */}
          <div className="max-h-[240px] overflow-y-auto rounded-md border p-2" onScroll={event => { const el = event.currentTarget; if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) search.loadMore() }}>
            {search.tooLong || search.failed || search.loading ? <SubjectSearchStatus tooLong={search.tooLong} failed={search.failed} loading={search.loading} onRetry={search.retry} /> : users.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">
                {keyword ? t("bs:subjectSearch.emptyUsers") : t("bs:department.searchMember")}
              </div>
            ) : (
              users.map((u) => (
                <div
                  key={u.user_id}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-accent"
                  onClick={() => toggleUser(u.user_id)}
                >
                  <Checkbox checked={selectedIds.has(u.user_id)} />
                  <span className="text-sm">{u.user_name}</span><SubjectBusinessId value={u.external_id} />
                </div>
              ))
            )}
          </div>

          {!search.loading && !search.failed && !search.tooLong && users.length < search.total && !!search.normalized && (
            <button type="button" onClick={search.loadMore}>{t("bs:subjectSearch.loadMore")}</button>
          )}

          {/* Selected count */}
          {selectedIds.size > 0 && (
            <p className="text-sm text-muted-foreground">
              {t("bs:department.selectMembers")}: {selectedIds.size}
            </p>
          )}

          {/* Primary/Secondary radio */}
          <div className="space-y-2">
            <Label>{t("bs:department.memberType")}</Label>
            <div className="flex gap-4">
              <label className="flex cursor-pointer items-center gap-1 text-sm">
                <input
                  type="radio"
                  value={1}
                  checked={isPrimary === 1}
                  onChange={() => setIsPrimary(1)}
                />
                {t("bs:department.primary")}
              </label>
              <label className="flex cursor-pointer items-center gap-1 text-sm">
                <input
                  type="radio"
                  value={0}
                  checked={isPrimary === 0}
                  onChange={() => setIsPrimary(0)}
                />
                {t("bs:department.secondary")}
              </label>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={loading || selectedIds.size === 0}>
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
