import MultiSelect from "@/components/bs-ui/select/multi";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { readFileLibDatabase } from "@/controllers/API";
import { getSelectableKnowledgeSpacesApi } from "@/controllers/API/knowledgeSpace";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const TabsHead = memo(({ onChange }: { onChange: (v: string) => void }) => {
    const { t } = useTranslation()

    return <Tabs defaultValue="file" className="mb-2" onValueChange={onChange}>
        <TabsList className="grid w-full grid-cols-2 py-1 max-w-80">
            <TabsTrigger value="file" className="text-xs">{t('lib.fileData')}</TabsTrigger>
            <TabsTrigger value="qa" className="text-xs">{t('lib.qaData')}</TabsTrigger>
        </TabsList>
    </Tabs>
})

// F041: file / knowledge-space tab head, opt-in via `enableSpace` (assistant app).
// Kept separate from the file/qa head so existing callers are untouched.
const SpaceTabsHead = memo(({ onChange }: { onChange: (v: string) => void }) => {
    const { t } = useTranslation()

    return <Tabs defaultValue="file" className="mb-2" onValueChange={onChange}>
        <TabsList className="grid w-full grid-cols-2 py-1 max-w-80">
            <TabsTrigger value="file" className="text-xs">{t('build.documentKnowledgeBase')}</TabsTrigger>
            <TabsTrigger value="space" className="text-xs">{t('build.knowledgeSpace')}</TabsTrigger>
        </TabsList>
    </Tabs>
})

const enum KnowledgeType {
    FILE = 'file',
    QA = 'qa',
    SPACE = 'space',
    ALL = 'all'
}
type KnowledgeTypeValues = `${KnowledgeType}`;

export default function KnowledgeSelect({
    type = KnowledgeType.ALL,
    multiple = false,
    className = '',
    value,
    disabled = false,
    // F041: opt-in second tab (文档知识库 + 知识空间) for the assistant app.
    // Selected items carry a `type` ('file' | 'space') so the two sources can be
    // told apart on echo (see design 决策 4 / 防坑 5.9: type='file' callers keep
    // the plain file list unless they explicitly opt in).
    enableSpace = false,
    onChange,
    children
}:
    { type?: KnowledgeTypeValues, multiple?: boolean, className?: string, value: any, disabled?: boolean, enableSpace?: boolean, onChange: (a: any) => any, children?: (fun: any) => React.ReactNode }) {

    const { t } = useTranslation()
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    // F041: knowledge spaces are loaded once (INV-6 exception, full-return) and
    // filtered client-side, matching the client daily-mode selector.
    const [spaceOptions, setSpaceOptions] = useState<any>([])
    const allSpacesRef = useRef<any[]>([])
    // value -> type lookup so a click (MultiSelect only echoes {label,value})
    // can be re-stamped with its source type before reaching the parent.
    const typeByValueRef = useRef<Map<any, KnowledgeTypeValues>>(new Map())
    const [tabType, setTabType] = useState<KnowledgeTypeValues>(KnowledgeType.FILE)

    // F027: cursor-based pagination. `page > 1` semantics replaced by
    // "do we have a cursor to fetch the next page?" The first call passes
    // `cursor=null` for the first page; subsequent calls pass `next_cursor`.
    const cursorRef = useRef<string | null>(null)
    const typeRef = useRef(type === 'qa' ? 1 : 0)
    const reload = (cursor: string | null, name: string) => {
        readFileLibDatabase({ cursor, pageSize: 60, name, type: typeRef.current, permissionId: 'use_kb' }).then(res => {
            cursorRef.current = res.next_cursor
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id, type: KnowledgeType.FILE }))
            opts.forEach(o => typeByValueRef.current.set(o.value, KnowledgeType.FILE))
            setOptions(_ops => cursor ? [..._ops, ...opts] : opts)
        })
    }

    // F041: load selectable knowledge spaces (mine + joined + department union).
    const loadSpaces = () => {
        getSelectableKnowledgeSpacesApi().then(spaces => {
            allSpacesRef.current = spaces.map(s => ({ label: s.name, value: s.id, type: KnowledgeType.SPACE }))
            allSpacesRef.current.forEach(o => typeByValueRef.current.set(o.value, KnowledgeType.SPACE))
            setSpaceOptions(allSpacesRef.current)
        })
    }
    const filterSpaces = (name: string) => {
        const kw = (name || '').toLowerCase()
        setSpaceOptions(allSpacesRef.current.filter(o => o.label.toLowerCase().includes(kw)))
    }

    useEffect(() => {
        reload(null, '')
        if (enableSpace) loadSpaces()
    }, [])

    // Seed the type lookup from the echoed value so pre-selected items keep their
    // source even before the space list finishes loading.
    useEffect(() => {
        (value || []).forEach((v: any) => {
            if (v && v.value != null && v.type) typeByValueRef.current.set(v.value, v.type)
        })
    }, [value])

    // const handleChange = (res) => {
    //     // id => obj
    //     onChange(res.map(el => originOptionsRef.current.find(el2 => el2.id === el)))
    // }

    // 加载更多
    const loadMore = (name) => {
        if (cursorRef.current) reload(cursorRef.current, name)
    }

    const handleTabChange = (val) => {
        setTabType(val)
        if (val === KnowledgeType.SPACE) {
            loadSpaces()
        } else {
            typeRef.current = val === 'qa' ? 1 : 0
            reload(null, '')
        }
        const inputDom = document.getElementById('knowledge-select')
        if (inputDom) {
            inputDom.value = ''
        }
    }

    // F041: re-stamp each selected item with its source type (file | space) so the
    // parent can persist and later echo it into the right tab.
    const handleChange = (vals) => {
        if (!enableSpace) return onChange(vals)
        onChange(vals.map((el: any) => ({
            ...el,
            type: el.type || typeByValueRef.current.get(el.value) || KnowledgeType.FILE
        })))
    }

    return <MultiSelect
        id="knowledge-select"
        tabs={enableSpace
            ? <SpaceTabsHead onChange={handleTabChange} />
            : type === KnowledgeType.ALL ? <TabsHead onChange={handleTabChange} /> : null}
        multiple={multiple}
        className={className}
        value={value}
        disabled={disabled}
        options={enableSpace && tabType === KnowledgeType.SPACE ? spaceOptions : options}
        placeholder={t('build.selectKnowledgeBase')}
        searchPlaceholder={t('build.searchBaseName')}
        onChange={handleChange}
        onLoad={() => {
            typeRef.current = type === 'qa' ? 1 : 0
            reload(null, '');
            if (enableSpace) loadSpaces();
        }}
        onSearch={(val) => (enableSpace && tabType === KnowledgeType.SPACE) ? filterSpaces(val) : reload(null, val)}
        onScrollLoad={(val) => { if (!(enableSpace && tabType === KnowledgeType.SPACE)) loadMore(val) }}
    >
        {children?.(reload)}
    </MultiSelect>
};
