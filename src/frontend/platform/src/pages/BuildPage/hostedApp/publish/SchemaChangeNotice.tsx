/**
 * Structure-change notice of the publish tab (AC-09 / AC-61).
 *
 * Read-only by design. The confirmation happened on the CLI at submit time —
 * this notice tells the owner (and an administrator reading the face) what the
 * pending release will do to the declared tables, so that "my data is gone"
 * after go-live is never a surprise. It renders nothing when there is nothing
 * to say: a title over an empty list reads as a broken card.
 */
import type { HostedAppSchemaChange } from "@/controllers/API/hostedApp"
import { AlertTriangle } from "lucide-react"
import { useTranslation } from "react-i18next"
import {
  hasSchemaChange,
  isBreakingOp,
  schemaChangeSummaryI18nKey,
  schemaChangeTarget,
  schemaOpI18nKey,
} from "./schemaChange"

interface SchemaChangeNoticeProps {
  change: HostedAppSchemaChange | null | undefined
}

export function SchemaChangeNotice({ change }: SchemaChangeNoticeProps) {
  const { t } = useTranslation()
  if (!hasSchemaChange(change)) return null

  return (
    <section
      data-testid="schema-change-notice"
      className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-950"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle
          aria-hidden="true"
          className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {t("hostedApp.publishStatus.schemaChangeTitle")}
          </p>
          <p className="mt-1 text-sm">{t(schemaChangeSummaryI18nKey(change))}</p>
          <ul className="mt-2 flex flex-col gap-1">
            {change.items.map((item, index) => {
              const breaking = isBreakingOp(item.op)
              return (
                <li
                  key={`${item.op}-${item.table}-${item.column ?? ""}-${index}`}
                  className="flex flex-wrap items-center gap-2 text-sm"
                >
                  <span className="rounded-sm bg-background px-1.5 py-0.5 text-xs">
                    {t(schemaOpI18nKey(item.op))}
                  </span>
                  <code className="break-all font-mono text-xs">
                    {schemaChangeTarget(item)}
                  </code>
                  {breaking && (
                    <span className="rounded-sm bg-red-100 px-1.5 py-0.5 text-xs text-red-700 dark:bg-red-900 dark:text-red-200">
                      {t("hostedApp.publishStatus.schemaChangeBreakingTag")}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </section>
  )
}
