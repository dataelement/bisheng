import { X } from "lucide-react"
import { type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { cname } from "@/components/bs-ui/utils"

interface ClearableFilterProps {
    hasValue: boolean
    label: string
    onClear: () => void
    children: ReactNode
    className?: string
    isDate?: boolean
}

export default function ClearableFilter({ hasValue, label, onClear, children, className, isDate = false }: ClearableFilterProps) {
    const { t } = useTranslation("dashboard")

    return <div className={cname(
        "relative",
        hasValue && (isDate
            ? "[&_button[aria-haspopup=dialog]]:pr-8"
            : "[&_[role=combobox]]:gap-6 [&_[role=combobox]>span]:min-w-0 [&_[role=combobox]>span]:truncate"),
        className,
    )}>
        {children}
        {hasValue && <button
            type="button"
            aria-label={`${t("clear")} ${label}`}
            title={`${t("clear")} ${label}`}
            className={cname(
                "absolute top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                isDate ? "right-2" : "right-8",
            )}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
                event.stopPropagation()
                onClear()
            }}
        >
            <X className="h-3.5 w-3.5" />
        </button>}
    </div>
}
