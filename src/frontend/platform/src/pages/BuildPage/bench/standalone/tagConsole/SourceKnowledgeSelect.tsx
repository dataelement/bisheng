import MultiSelect from "@/components/bs-ui/select/multi"
import { listTagConsoleSourceKnowledgesApi } from "@/controllers/API/knowledgeSpaceTagLibrary"
import { useCallback, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

interface Option {
    label: string
    value: string
}

interface SourceKnowledgeSelectProps {
    value: { label: string; value: string }[]
    onChange: (options: Option[]) => void
}

/**
 * Picker for 标签来源库.
 *
 * Deliberately not the shared knowledge picker. That one lists knowledge bases
 * by type, which here meant either a single entry (it defaults to the normal
 * type, while tags come from knowledge spaces) or, once pointed at spaces,
 * dozens of useless ones — every user owns a personal space and a 『我的收藏』,
 * so the dropdown filled with repeated names that could never match a tag.
 *
 * The console asks instead for the knowledge bases that have actually produced
 * tags. They come back distinct by id and 『我的收藏』 is excluded server-side,
 * so what is offered is exactly what can return results.
 */
export function SourceKnowledgeSelect({ value, onChange }: SourceKnowledgeSelectProps) {
    const { t } = useTranslation()
    const [options, setOptions] = useState<Option[]>([])
    // Guards against a second load starting before the first returns, which
    // would otherwise append the same rows again.
    const loadingRef = useRef(false)

    const load = useCallback(async (keyword: string) => {
        if (loadingRef.current) return
        loadingRef.current = true
        try {
            const res = await listTagConsoleSourceKnowledgesApi(keyword)
            setOptions((res?.data || []).map((item) => ({ label: item.name, value: String(item.id) })))
        } finally {
            loadingRef.current = false
        }
    }, [])

    return (
        <div className="relative w-[200px]">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={options}
                value={value}
                placeholder={t("build.tagConsole.selectKnowledge", "请选择知识库")}
                onLoad={() => load("")}
                onSearch={(keyword: string) => load(keyword)}
                // Present, but nothing to fetch: the server caps the list and
                // there is no second page. It also selects the control's
                // option-shaped value mode, which is what lets the closed box
                // show the picked name without the option still being loaded.
                onScrollLoad={() => undefined}
                onChange={onChange}
            />
        </div>
    )
}
