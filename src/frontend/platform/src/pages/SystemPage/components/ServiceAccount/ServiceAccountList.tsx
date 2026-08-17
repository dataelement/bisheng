import { PlusIcon } from "@/components/bs-icons"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { getServiceAccountsApi } from "@/controllers/API/serviceAccount"
import { ServiceAccountItem } from "@/types/api/serviceAccount"
import { useTable } from "@/util/hook"
import { formatIsoDateTime } from "@/util/utils"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { CreateServiceAccountDialog } from "./CreateServiceAccountDialog"

interface ServiceAccountListProps {
  onOpenDetail: (id: number) => void
  /** Creation jumps straight to the detail page's key tab, not back to the list (AC-43). */
  onCreated: (id: number) => void
}

const COLUMN_COUNT = 7

/**
 * Service-account list (AC-42 columns).
 *
 * `idle_days` is deployment configuration and arrives with the same response as
 * the `idle` flag, so it is read from the payload and never hardcoded here.
 */
export function ServiceAccountList({ onOpenDetail, onCreated }: ServiceAccountListProps) {
  const { t } = useTranslation("serviceAccount")
  const [idleDays, setIdleDays] = useState<number | null>(null)
  const [openCreate, setOpenCreate] = useState(false)

  const { page, pageSize, data, total, loading, setPage, search } = useTable<ServiceAccountItem>(
    { pageSize: 20 },
    (param: { page: number; pageSize: number; keyword: string }) =>
      getServiceAccountsApi({
        page: param.page,
        pageSize: param.pageSize,
        keyword: param.keyword,
      }).then((res) => {
        setIdleDays(res.idle_days)
        return res
      })
  )

  const renderOwner = (item: ServiceAccountItem) => {
    if (!item.resource_owner) return <span className="text-gray-400">{t("list.unknownUser")}</span>
    const disabled = item.owner_disabled || item.resource_owner.disabled
    return (
      <div className="flex items-center gap-1">
        <span className={disabled ? "text-red-500" : ""}>
          {item.resource_owner.user_name || t("list.unknownUser")}
        </span>
        {disabled && <QuestionTooltip error content={t("list.ownerDisabledTip")} />}
      </div>
    )
  }

  const renderLastUsed = (item: ServiceAccountItem) => {
    const idleTip =
      item.idle && idleDays !== null ? (
        <QuestionTooltip content={t("list.idleTip", { days: idleDays })} />
      ) : null
    if (!item.last_used_at) {
      return (
        <div className="flex items-center gap-1">
          <span className="text-gray-400">{t("list.neverUsed")}</span>
          {idleTip}
        </div>
      )
    }
    return (
      <div className="flex items-center gap-1">
        <span>{formatIsoDateTime(item.last_used_at)}</span>
        {idleTip}
      </div>
    )
  }

  return (
    <div className="relative flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto pb-10">
        <div className="flex justify-end gap-6">
          <div className="relative w-[240px]">
            <SearchInput
              placeholder={t("list.searchPlaceholder")}
              onChange={(e) => search(e.target.value)}
            />
          </div>
          <Button className="flex justify-around" onClick={() => setOpenCreate(true)}>
            <PlusIcon className="text-primary" />
            <span className="mx-4 text-[#fff]">{t("list.create")}</span>
          </Button>
        </div>
        <Table className="mb-[50px]">
          <TableHeader>
            <TableRow>
              <TableHead>{t("list.columns.name")}</TableHead>
              <TableHead>{t("list.columns.status")}</TableHead>
              <TableHead>{t("list.columns.activeKeyCount")}</TableHead>
              <TableHead>{t("list.columns.resourceOwner")}</TableHead>
              <TableHead>{t("list.columns.lastUsedAt")}</TableHead>
              <TableHead>{t("list.columns.createdBy")}</TableHead>
              <TableHead>{t("list.columns.createTime")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((item) => (
              <TableRow
                key={item.id}
                className="cursor-pointer"
                onClick={() => onOpenDetail(item.id)}
              >
                <TableCell className="max-w-[220px] truncate font-medium">{item.name}</TableCell>
                <TableCell>{t(`status.${item.status}`)}</TableCell>
                <TableCell>
                  {item.active_key_count === 0 ? (
                    <div className="flex items-center gap-1">
                      <span className="text-red-500">0</span>
                      <QuestionTooltip error content={t("list.noKeyTip")} />
                    </div>
                  ) : (
                    item.active_key_count
                  )}
                </TableCell>
                <TableCell>{renderOwner(item)}</TableCell>
                <TableCell>{renderLastUsed(item)}</TableCell>
                <TableCell className="max-w-[160px] truncate">
                  {item.creator_name || t("list.unknownUser")}
                </TableCell>
                <TableCell>{formatIsoDateTime(item.create_time)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            {!loading && !data.length && (
              <TableRow>
                <TableCell colSpan={COLUMN_COUNT} className="text-center text-gray-400">
                  {t("list.empty")}
                </TableCell>
              </TableRow>
            )}
          </TableFooter>
        </Table>
      </div>
      <div className="bisheng-table-footer bg-background-login px-6">
        <AutoPagination
          className="float-right mr-6 w-full justify-end"
          page={page}
          pageSize={pageSize}
          total={total}
          showTotal
          onChange={(newPage) => setPage(newPage)}
        />
      </div>
      <CreateServiceAccountDialog
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        onCreated={(id) => {
          setOpenCreate(false)
          onCreated(id)
        }}
      />
    </div>
  )
}
