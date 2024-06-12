import MultiSelect from "@/components/bs-ui/select/multi";
import { readFileLibDatabase } from "@/controllers/API";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function KnowledgeSelect({ multiple = false, value, disabled = false, onChange, children }:
    { multiple?: boolean, value: any, disabled?: boolean, onChange: (a: any) => any, children?: (fun: any) => React.ReactNode }) {

    const { t } = useTranslation()
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const pageRef = useRef(1)
    const reload = (page, name) => {
        readFileLibDatabase(page, 60, name).then(res => {
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

    return <MultiSelect
        multiple={multiple}
        value={value}
        disabled={disabled}
        options={options}
        placeholder={t('build.selectKnowledgeBase')}
        searchPlaceholder={t('build.searchBaseName')}
        onChange={onChange}
        onLoad={() => reload(1, '')}
        onSearch={(val) => reload(1, val)}
        onScrollLoad={(val) => loadMore(val)}
    >
        {children?.(reload)}
    </MultiSelect>
};
