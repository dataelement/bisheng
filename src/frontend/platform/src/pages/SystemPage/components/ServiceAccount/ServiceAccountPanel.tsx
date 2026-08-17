import { useState } from "react"
import { ServiceAccountDetail } from "./ServiceAccountDetail"
import { ServiceAccountList } from "./ServiceAccountList"

export type ServiceAccountDetailTab = "overview" | "keys" | "grants"

/**
 * Tab container for the service-account module.
 *
 * `SystemPage` tabs are plain `<TabsContent>` bodies with no child routes, so
 * list ↔ detail is local state rather than navigation. Leaving the detail
 * unmounts it and remounts the list, which refetches — that is also what keeps
 * the page consistent after a super admin switches tenant scope elsewhere.
 */
export function ServiceAccountPanel() {
  const [view, setView] = useState<"list" | "detail">("list")
  const [detailId, setDetailId] = useState<number | null>(null)
  const [detailInitialTab, setDetailInitialTab] = useState<ServiceAccountDetailTab>("overview")
  const [autoOpenIssue, setAutoOpenIssue] = useState(false)

  const openDetail = (id: number) => {
    setDetailId(id)
    setDetailInitialTab("overview")
    setAutoOpenIssue(false)
    setView("detail")
  }

  // Creation lands on the key tab with the issue dialog already open (AC-43).
  const openFreshAccount = (id: number) => {
    setDetailId(id)
    setDetailInitialTab("keys")
    setAutoOpenIssue(true)
    setView("detail")
  }

  const backToList = () => {
    setView("list")
    setDetailId(null)
    setAutoOpenIssue(false)
  }

  if (view === "detail" && detailId !== null) {
    return (
      <ServiceAccountDetail
        id={detailId}
        initialTab={detailInitialTab}
        autoOpenIssue={autoOpenIssue}
        onBack={backToList}
      />
    )
  }

  return <ServiceAccountList onOpenDetail={openDetail} onCreated={openFreshAccount} />
}
