"use client"

// F058 AC-09/AC-10: drill-down (one category) and whole-chart Excel export.

import { useToast } from "@/components/bs-ui/toast/use-toast"
import { exportComponentAll, exportComponentDetail } from "@/controllers/API/dashboard"
import { useEditorDashboardStore } from "@/store/dashboardStore"
import { useState } from "react"
import { useTranslation } from "react-i18next"

interface UseComponentExportArgs {
  dashboardId: string
  componentId: string
  timeFilters?: any[]
  dimensionFilters?: { fieldId: string, values: unknown[] }[]
}

function downloadFile(url: string) {
  // Opens the MinIO-hosted file in a new tab; the browser handles the actual download
  // via the response's content-disposition, matching how other export flows in this
  // app (e.g. QA export) hand a file_url back to the caller.
  window.open(url, "_blank", "noopener,noreferrer")
}

export function useComponentExport({
  dashboardId,
  componentId,
  timeFilters,
  dimensionFilters,
}: UseComponentExportArgs) {
  const { t } = useTranslation("dashboard")
  const { toast } = useToast()
  const savedDashboard = useEditorDashboardStore(state => state.savedDashboard)
  const [exportingDetailKey, setExportingDetailKey] = useState<string | null>(null)
  const [exportingAll, setExportingAll] = useState(false)

  // Export reads the component's saved configuration from the server by id, so a chart the
  // editor has created (or a dashboard whose changes aren't committed) has nothing to read
  // — the request comes back "资源不存在". Compare against savedDashboard, the last
  // server-confirmed state, and ask the user to save instead of showing that error.
  const canExport = Boolean(
    dashboardId
    && componentId
    && savedDashboard?.components?.some(component => component.id === componentId)
  )

  const warnUnsaved = () => {
    toast({ description: t("componentExport.saveBeforeExport"), variant: "error" })
  }

  const exportDetail = async (dimensionField: string, dimensionValue: string | number) => {
    if (!canExport) return warnUnsaved()
    const key = `${dimensionField}:${dimensionValue}`
    setExportingDetailKey(key)
    try {
      const { file_url } = await exportComponentDetail({
        dashboardId,
        componentId,
        dimensionField,
        dimensionValue,
        timeFilters,
        dimensionFilters,
      })
      downloadFile(file_url)
    } catch (error) {
      console.error("exportComponentDetail failed:", error)
      toast({ description: t("componentExport.exportFailed"), variant: "error" })
    } finally {
      setExportingDetailKey(null)
    }
  }

  const exportAll = async () => {
    if (!canExport) return warnUnsaved()
    setExportingAll(true)
    try {
      const { file_url } = await exportComponentAll({
        dashboardId,
        componentId,
        timeFilters,
        dimensionFilters,
      })
      downloadFile(file_url)
    } catch (error) {
      console.error("exportComponentAll failed:", error)
      toast({ description: t("componentExport.exportFailed"), variant: "error" })
    } finally {
      setExportingAll(false)
    }
  }

  return {
    exportDetail,
    exportAll,
    canExport,
    isExportingDetail: (dimensionField: string, dimensionValue: string | number) =>
      exportingDetailKey === `${dimensionField}:${dimensionValue}`,
    isExportingAll: exportingAll,
  }
}
