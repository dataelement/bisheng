import MultiSelect from "@/components/bs-ui/select/multi";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { readFileLibDatabase } from "@/controllers/API";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const TabsHead = memo(({ onChange }) => {

    return <Tabs defaultValue="file" className="mb-2" onValueChange={onChange}>
        <TabsList className="grid w-full grid-cols-2 py-1 max-w-80">
            <TabsTrigger value="file" className="text-xs">文档知识库</TabsTrigger>
            <TabsTrigger value="qa" className="text-xs">QA知识库</TabsTrigger>
        </TabsList>
    </Tabs>
})

const enum KnowledgeType {
    FILE = 'file',
    QA = 'qa',
    ALL = 'all'
}
type KnowledgeTypeValues = `${KnowledgeType}`;

export default function KnowledgeSelect({
    type = KnowledgeType.ALL,
    multiple = false,
    className = '',
    value,
    disabled = false,
    onChange,
    children
}:
    { type?: KnowledgeTypeValues, multiple?: boolean, className?: string, value: any, disabled?: boolean, onChange: (a: any) => any, children?: (fun: any) => React.ReactNode }) {

    const { t } = useTranslation()
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const pageRef = useRef(1)
    const typeRef = useRef(type === 'qa' ? 1 : 0)
    const reload = (page, name) => {
        readFileLibDatabase({ page, pageSize: 60, name, type: typeRef.current }).then(res => {
            pageRef.current = page
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => page > 1 ? [..._ops, ...opts] : opts)
        })
    }

    useEffect(() => {
        reload(1, '')
    }, [])

    // const handleChange = (res) => {
    //     // id => obj
    //     onChange(res.map(el => originOptionsRef.current.find(el2 => el2.id === el)))
    // }

    // 加载更多
    const loadMore = (name) => {
        reload(pageRef.current + 1, name)
    }

    const handleTabChange = (val) => {
        typeRef.current = val === 'qa' ? 1 : 0
        reload(1, '')
        const inputDom = document.getElementById('knowledge-select')
        if (inputDom) {
            inputDom.value = ''
        }
    }

    return <MultiSelect
        id="knowledge-select"
        tabs={type === KnowledgeType.ALL ? <TabsHead onChange={handleTabChange} /> : null}
        multiple={multiple}
        className={className}
        value={value}
        disabled={disabled}
        options={options}
        placeholder={t('build.selectKnowledgeBase')}
        searchPlaceholder={t('build.searchBaseName')}
        onChange={onChange}
        onLoad={() => {
            typeRef.current = type === 'qa' ? 1 : 0
            reload(1, '');
        }}
        onSearch={(val) => reload(1, val)}
        onScrollLoad={(val) => loadMore(val)}
    >
        {children?.(reload)}
    </MultiSelect>
};
