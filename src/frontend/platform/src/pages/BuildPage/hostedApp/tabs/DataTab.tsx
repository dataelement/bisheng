/**
 * Data tab — shell only in this release.
 *
 * The application's own database (view / edit / export, no DDL) is WB-06 and
 * lands in a later wave; the tab exists now so the four-tab shell is complete
 * and the later work is a fill-in rather than a layout change.
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
