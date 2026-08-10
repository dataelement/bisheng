import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip"
import { Bot, Hash, User } from "lucide-react"
import { useTranslation } from "react-i18next"

/** Distinguishes the three tag sources by icon, as the prototype asks for. */
export function TagSourceIcon({ resourceType }: { resourceType: string }) {
    const { t } = useTranslation()

    const { Icon, label, className } =
        resourceType === "ai_auto_tag"
            ? { Icon: Bot, label: t("build.tagSourceAi", "AI标签"), className: "text-[#7C3AED]" }
            : resourceType === "system_tag"
              ? { Icon: Hash, label: t("build.tagSourceSystem", "系统标签"), className: "text-[#0EA5E9]" }
              : { Icon: User, label: t("build.tagSourceManual", "人工标签"), className: "text-[#16A34A]" }

    return (
        <TooltipProvider delayDuration={200}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span className={`mr-1 inline-flex align-middle ${className}`}>
                        <Icon className="size-3.5" />
                    </span>
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    )
}

export function tagSourceLabel(resourceType: string, t: (key: string, fallback: string) => string) {
    if (resourceType === "ai_auto_tag") return t("build.tagSourceAi", "AI标签")
    if (resourceType === "system_tag") return t("build.tagSourceSystem", "系统标签")
    return t("build.tagSourceManual", "人工标签")
}
