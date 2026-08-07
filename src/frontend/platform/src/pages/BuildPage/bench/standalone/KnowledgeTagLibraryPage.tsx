// Standalone page for the workbench "auto tag generation / tag library" section.
// Mounted at /standalone/knowledge-tag-library without the platform shell.
import { Button } from "@/components/bs-ui/button"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import { getKnowledgeConfigApi, setKnowledgeConfigApi } from "@/controllers/API"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import ConfigInheritanceBanner, { resolveConfigEnvelope } from "../ConfigInheritanceBanner"
import KnowledgeSpaceTagSection from "../KnowledgeSpaceTagLibrarySection"
import { resolveConfigString } from "../configValue"

/**
 * Sibling fields of the knowledge workbench config that this page does not edit.
 * They are read on mount and written back verbatim on save, because the config
 * API replaces the whole object — omitting them would wipe the saved values.
 */
interface PreservedKnowledgeConfig {
    systemPrompt: string
    userPrompt: string
    maxChunkSize: number
    reviewTagVisible: boolean
}

const DEFAULT_PRESERVED: PreservedKnowledgeConfig = {
    systemPrompt: "",
    userPrompt: "",
    maxChunkSize: 15000,
    reviewTagVisible: false,
}

export default function KnowledgeTagLibraryPage() {
    const { t } = useTranslation()
    const { toast } = useToast()
    const { reloadConfig } = useContext(locationContext)
    const [autoTagVisible, setAutoTagVisible] = useState(false)
    const [configMeta, setConfigMeta] = useState<any>(null)
    const [loaded, setLoaded] = useState(false)
    const preservedRef = useRef<PreservedKnowledgeConfig>(DEFAULT_PRESERVED)

    useEffect(() => {
        getKnowledgeConfigApi().then((res) => {
            const { data: envData, meta } = resolveConfigEnvelope<Record<string, unknown>>(res)
            const cfg = envData != null && typeof envData === "object" ? envData : null
            const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens
            preservedRef.current = {
                systemPrompt:
                    resolveConfigString(cfg?.system_prompt ?? cfg?.systemPrompt, "") ||
                    t("chatConfig.aiPrompt"),
                userPrompt:
                    resolveConfigString(cfg?.user_prompt ?? cfg?.userPrompt, "") ||
                    t("chatConfig.retrievedAndQuestion"),
                maxChunkSize:
                    typeof maxChunkSizeFromRes === "number"
                        ? maxChunkSizeFromRes
                        : DEFAULT_PRESERVED.maxChunkSize,
                reviewTagVisible: Boolean(cfg?.review_tag_visible ?? cfg?.reviewTagVisible),
            }
            setConfigMeta(meta)
            setAutoTagVisible(Boolean(cfg?.auto_tag_visible ?? cfg?.autoTagVisible))
            setLoaded(true)
        })
    }, [t])

    const handleSave = async () => {
        if (!loaded) return
        const preserved = preservedRef.current
        const res = await captureAndAlertRequestErrorHoc(
            setKnowledgeConfigApi({
                system_prompt: preserved.systemPrompt,
                user_prompt: preserved.userPrompt,
                max_chunk_size: preserved.maxChunkSize,
                review_tag_visible: preserved.reviewTagVisible,
                auto_tag_visible: autoTagVisible,
            }),
        )
        if (res) {
            setConfigMeta({ inherited_from_root: false, has_override: true })
            toast({ variant: "success", description: t("chatConfig.saveSuccess") })
            reloadConfig()
        }
    }

    return (
        <div className="relative flex h-full flex-col px-2 pt-4">
            <div className="flex-1 overflow-y-auto scrollbar-hide pb-16">
                <ConfigInheritanceBanner meta={configMeta} />
                <KnowledgeSpaceTagSection visible={autoTagVisible} onToggle={setAutoTagVisible} />
            </div>
            <div className="absolute bottom-2 right-4">
                <Button onClick={handleSave}>{t("save")}</Button>
            </div>
        </div>
    )
}
