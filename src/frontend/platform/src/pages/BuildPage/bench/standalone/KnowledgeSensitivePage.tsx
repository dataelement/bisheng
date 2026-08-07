// Standalone page for the workbench "content security review" section.
// Mounted at /standalone/content-security without the platform shell.
// The sensitive-word policy owns its own API, so this page only adds the
// save trigger that the workbench tab used to provide.
import { Button } from "@/components/bs-ui/button"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useRef } from "react"
import { useTranslation } from "react-i18next"
import {
    KnowledgeSpaceSensitivePolicy,
    type KnowledgeSpaceSensitivePolicyHandle,
} from "../KnowledgeSpaceSensitivePolicy"

export default function KnowledgeSensitivePage() {
    const { t } = useTranslation()
    const { toast } = useToast()
    const sensitivePolicyRef = useRef<KnowledgeSpaceSensitivePolicyHandle>(null)

    const handleSave = async () => {
        const saved = await sensitivePolicyRef.current?.save()
        if (saved) {
            toast({ variant: "success", description: t("chatConfig.saveSuccess") })
        }
    }

    return (
        <div className="relative flex h-full flex-col px-2 pt-4">
            <div className="flex-1 overflow-y-auto scrollbar-hide pb-16">
                <KnowledgeSpaceSensitivePolicy ref={sensitivePolicyRef} />
            </div>
            <div className="absolute bottom-2 right-4">
                <Button onClick={handleSave}>{t("save")}</Button>
            </div>
        </div>
    )
}
