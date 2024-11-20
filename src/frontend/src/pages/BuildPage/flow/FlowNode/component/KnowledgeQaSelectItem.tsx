import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { readFileLibDatabase } from "@/controllers/API";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";


export default function KnowledgeQaSelectItem({ data, onChange, onValidate }) {
    const { t } = useTranslation()
    const [value, setValue] = useState<any>(() => data.value.map(el => {
        return { label: el.label, value: el.key }
    }))
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const pageRef = useRef(1)
    const reload = (page, name) => {
        readFileLibDatabase({ page, pageSize: 60, name, type: 1 }).then(res => {
            pageRef.current = page
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => page > 1 ? [..._ops, ...opts] : opts)
        })
    }


    useEffect(() => {
        reload(1, '')
    }, [])

    // 加载更多
    const loadMore = (name) => {
        reload(pageRef.current + 1, name)
    }

    const handleSelect = (resVals) => {
        setValue(resVals)
        onChange(resVals.map(el => ({
            key: el.value,
            label: el.label
        }))
        )
    }

    const [error, setError] = useState(false)
    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value.length) {
                setError(true)
                return data.label + '不可为空'
            }
            setError(false)
            return false
        })
        
        return () => onValidate(() => {})
    }, [data.value])

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}
            {data.label}
        </Label>
        <MultiSelect
            id="knowledge-qaselect"
            error={error}
            multiple
            className={''}
            value={value}
            options={options}
            placeholder={t('build.selectKnowledgeBase')}
            searchPlaceholder={t('build.searchBaseName')}
            onChange={handleSelect}
            onLoad={() => reload(1, '')}
            onSearch={(val) => reload(1, val)}
            onScrollLoad={(val) => loadMore(val)}
        >
            {/* {children?.(reload)} */}
        </MultiSelect>
    </div>
};
