import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getKnowledgeDetailApi, readFileLibDatabase } from "@/controllers/API";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";

const PAGE_SIZE = 60

const mergeOptionsByValue = (currentOptions, nextOptions) => {
    const existingValues = new Set(currentOptions.map(option => option.value))
    return [
        ...currentOptions,
        ...nextOptions.filter(option => !existingValues.has(option.value))
    ]
}


export default function KnowledgeQaSelectItem({ nodeId, data, onChange, onValidate, onVarEvent, i18nPrefix }) {
    const { t } = useTranslation('flow')
    const { flow } = useFlowStore()
    const [value, setValue] = useState<any>(() => data.value.map(el => {
        return { label: el.label, value: el.key }
    }))
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const cursorRef = useRef<string | null>(null)
    const requestSeqRef = useRef(0)
    const reload = (cursor: string | null, name: string) => {
        const requestSeq = ++requestSeqRef.current
        readFileLibDatabase({ cursor, pageSize: PAGE_SIZE, name, type: 1, permissionId: 'use_kb' }).then(res => {
            if (requestSeq !== requestSeqRef.current) return
            cursorRef.current = res.next_cursor
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => cursor ? mergeOptionsByValue(_ops, opts) : opts)
        })
    }


    useEffect(() => {
        reload(null, '')
    }, [])

    // 加载更多
    const loadMore = (name) => {
        if (cursorRef.current) reload(cursorRef.current, name)
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
                return t(`${i18nPrefix}label`) + ' ' + t('required')
            }
            if (data.value.some(item => /input_[a-zA-Z0-9]+\.file/.test(item.key))) {
                return 'input_file'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { })
    }, [data.value])

    // 校验变量是否可用
    const [errorKeys, setErrorKeys] = useState<string[]>([])
    const validateVarAvailble = async () => {
        if (!value.length) return ''
        let error = '';
        const _errorKeys = [];
        const effectiveKnowledges = await getKnowledgeDetailApi(value.map(el => el.value));
        for (const el of value) {
            // If not found, check against effectiveKnowledges
            if (!effectiveKnowledges.some(base => base.id === el.value)) {
                // error = t('nodeErrorMessage', {
                //     ns: 'flow',
                //     nodeName: flow.nodes.find(node => node.id === nodeId).data.name,
                //     varNameCn: ''
                // });
                error = `${flow.nodes.find(node => node.id === nodeId).data.name} ${t('nodeError')}: ${el.label} ${t('doesNotExist')}.`
                error && _errorKeys.push(el.value);
            }
            setErrorKeys(_errorKeys);
        }
        return error;
    };
    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble);
        return () => onVarEvent && onVarEvent(() => { });
    }, [data, value]);

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}
            {t(`${i18nPrefix}label`)}
        </Label>
        <MultiSelect
            id="knowledge-qaselect"
            error={error}
            errorKeys={errorKeys}
            multiple
            className={''}
            value={value}
            options={options}
            placeholder={t(`${i18nPrefix}placeholder`)}
            searchPlaceholder={t('build.searchBaseName', { ns: 'bs' })}
            onChange={handleSelect}
            onLoad={() => reload(null, '')}
            onSearch={(val) => reload(null, val)}
            onScrollLoad={(val) => loadMore(val)}
        >
            {/* {children?.(reload)} */}
        </MultiSelect>
    </div>
};
