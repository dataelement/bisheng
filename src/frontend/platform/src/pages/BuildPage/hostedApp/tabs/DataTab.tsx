/**
 * Data tab — built, but **not mounted** in this release.
 *
 * The application's own database (view / edit / export, no DDL) is WB-06 and
 * lands in a later wave. Until it does, this tab has nothing but a sentence
 * saying so, and a permanently empty tab in the detail page's tab strip is
 * worse than no tab: it advertises a missing feature to the owner on every
 * visit and costs a click to discover that it is still missing. It was
 * therefore removed from `TABS` and from the trigger row in `../index.tsx`
 * (2026-08-19).
 *
 * The file and its `contentSlot` stay exactly as they are on purpose. Bringing
 * the tab back when the data plane lands is then one entry in `TABS`, one
 * `TabsTrigger`, one `TabsContent` — a fill-in, not a layout rebuild — and the
 * `hostedApp.data.*` / `hostedApp.detail.tabs.data` copy stays in the three
 * locale files so nothing has to be re-translated (and `check-i18n` sees no
 * churn).
 */
import { useTranslation } from "react-i18next"

interface DataTabProps {
  /** Filled by the data-plane wave. */
  contentSlot?: React.ReactNode
}

export function DataTab({ contentSlot = null }: DataTabProps) {
  const { t } = useTranslation()

  if (contentSlot) return <div className="pb-6">{contentSlot}</div>

  return (
    <div className="flex h-40 items-center justify-center rounded-md border bg-background-login">
      <p className="text-sm text-muted-foreground">
        {t("hostedApp.data.placeholder")}
      </p>
    </div>
  )
}
