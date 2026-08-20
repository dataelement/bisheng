import type {
  LocalMemberDeleteExecuteResult,
  LocalMemberDeletePreview,
  LocalMemberDeleteReceiverPreview,
} from "@/controllers/API/department"
import type { TFunction } from "i18next"
import type { ReactNode } from "react"

const TRANSFER_ASSET_TYPES = [
  "knowledge_space",
  "folder",
  "knowledge_file",
  "workflow",
  "assistant",
  "tool",
  "channel",
] as const

const LINSIGHT_ASSET_TYPES = [
  "linsight_session_version",
  "linsight_sop",
  "linsight_sop_record",
] as const

function formatAssetLines(
  counts: Record<string, number>,
  types: readonly string[],
  t: TFunction
): string[] {
  return types
    .map((type) => ({ type, count: counts[type] ?? 0 }))
    .filter(({ count }) => count > 0)
    .map(({ type, count }) =>
      t(`bs:department.deleteLocalMemberAsset.${type}`, { count })
    )
}

export function formatLocalMemberDeleteReceiverLabel(
  receiver: LocalMemberDeleteReceiverPreview,
  t: TFunction
): string {
  if (receiver.source === "department_admin") {
    return t("bs:department.deleteLocalMemberReceiverDepartmentAdmin", {
      userName: receiver.user_name,
      departmentName: receiver.department_name ?? "-",
    })
  }
  return t("bs:department.deleteLocalMemberReceiverPlatformAdmin", {
    userName: receiver.user_name,
  })
}

export function buildLocalMemberDeleteConfirmDesc(
  preview: LocalMemberDeletePreview,
  t: TFunction
): ReactNode {
  const transferLines = formatAssetLines(preview.counts, TRANSFER_ASSET_TYPES, t)
  const linsightLines = formatAssetLines(preview.counts, LINSIGHT_ASSET_TYPES, t)

  return (
    <div className="space-y-3 text-left">
      <p>{t("bs:department.deleteLocalMemberConfirm")}</p>
      {preview.transfer_count > 0 && preview.proposed_receiver && transferLines.length > 0 && (
        <div>
          <p className="font-medium">
            {t("bs:department.deleteLocalMemberTransferSection", {
              receiver: formatLocalMemberDeleteReceiverLabel(preview.proposed_receiver, t),
            })}
          </p>
          <ul className="mt-1 list-inside list-disc text-sm">
            {transferLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {preview.linsight_delete_count > 0 && linsightLines.length > 0 && (
        <div>
          <p className="font-medium">{t("bs:department.deleteLocalMemberLinsightSection")}</p>
          <ul className="mt-1 list-inside list-disc text-sm">
            {linsightLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function buildLocalMemberDeleteSuccessDescription(
  result: LocalMemberDeleteExecuteResult,
  t: TFunction
): string {
  const parts = [t("bs:department.deleteLocalMemberDone")]

  if (result.transfer.performed && result.transfer.receiver) {
    parts.push(
      t("bs:department.deleteLocalMemberDoneTransferred", {
        count: result.transfer.transferred_count,
        receiver: formatLocalMemberDeleteReceiverLabel(result.transfer.receiver, t),
      })
    )
  }

  if (result.linsight_deleted.performed && result.linsight_deleted.deleted_count > 0) {
    parts.push(
      t("bs:department.deleteLocalMemberDoneLinsight", {
        count: result.linsight_deleted.deleted_count,
      })
    )
  }

  if (
    result.personal_recycled?.performed &&
    result.personal_recycled.recycled_count > 0 &&
    result.personal_recycled.folder_name
  ) {
    parts.push(
      t("bs:department.deleteLocalMemberDonePersonalRecycled", {
        count: result.personal_recycled.recycled_count,
        folderName: result.personal_recycled.folder_name,
      })
    )
  }

  return parts.join(" ")
}
