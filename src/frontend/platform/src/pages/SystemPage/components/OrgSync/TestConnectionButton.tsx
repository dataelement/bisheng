import { LoadButton } from "@/components/bs-ui/button"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useOrgSyncStore } from "@/store/orgSyncStore"
import { useState } from "react"
import { useTranslation } from "react-i18next"

interface TestConnectionButtonProps {
  configId: number
}

export function TestConnectionButton({ configId }: TestConnectionButtonProps) {
  const { t } = useTranslation("orgSync")
  const { message } = useToast()
  const testConnection = useOrgSyncStore((s) => s.testConnection)
  const [loading, setLoading] = useState(false)

  const handleClick = async () => {
    setLoading(true)
    try {
      const result = await captureAndAlertRequestErrorHoc(
        testConnection(configId)
      )
      if (result && result !== false) {
        message({
          title: t("testConnection.successTitle"),
          description: t("testConnection.successDesc", {
            org: result.org_name,
            depts: result.total_depts,
            members: result.total_members,
          }),
          variant: "success",
        })
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <LoadButton
      size="sm"
      variant="outline"
      loading={loading}
      onClick={handleClick}
    >
      {t("actions.test")}
    </LoadButton>
  )
}
