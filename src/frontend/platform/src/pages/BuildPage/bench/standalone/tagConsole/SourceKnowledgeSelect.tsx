import MultiSelect from "@/components/bs-ui/select/multi"
import { readFileLibDatabase } from "@/controllers/API"
import { useCallback, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

/** Knowledge *spaces*, which is where tags are proposed from. */
const KNOWLEDGE_SPACE_TYPE = 3
const PAGE_SIZE = 60

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
 * Deliberately not the shared `KnowledgeSelect`: that one only offers the
 * normal/QA knowledge bases (`type` 0 and 1), while every tag in this console
 * comes from a knowledge space (`type` 3). Pointing it at the wrong type made
 * the dropdown show a single entry.
 *
 * Scope is whatever the caller may use, so an admin sees the whole set.
 */
export function SourceKnowledgeSelect({ value, onChange }: SourceKnowledgeSelectProps) {
    const { t } = useTranslation()
    const [options, setOptions] = useState<Option[]>([])
    const cursorRef = useRef<string | null>(null)
    const keywordRef = useRef("")

    const load = useCallback(async (cursor: string | null, name: string) => {
        const res = await readFileLibDatabase({
            cursor,
            pageSize: PAGE_SIZE,
            name,
            type: KNOWLEDGE_SPACE_TYPE,
            permissionId: "use_kb",
        })
        cursorRef.current = res?.next_cursor ?? null
        keywordRef.current = name
        const rows = (res?.data || []).map((item: { id: number; name: string }) => ({
            label: item.name,
            value: String(item.id),
        }))
        // Appending only when paging keeps a fresh search from being merged
        // into the previous result set.
        setOptions((prev) => (cursor ? [...prev, ...rows] : rows))
    }, [])

    return (
        <div className="relative w-[200px]">
            <MultiSelect
                contentClassName="overflow-y-auto max-w-[200px]"
                options={options}
                value={value}
                placeholder={t("build.tagConsole.selectKnowledge", "请选择知识库")}
                onLoad={() => load(null, "")}
                onSearch={(keyword: string) => load(null, keyword)}
                onScrollLoad={() => cursorRef.current && load(cursorRef.current, keywordRef.current)}
                onChange={onChange}
            />
        </div>
    )
}
