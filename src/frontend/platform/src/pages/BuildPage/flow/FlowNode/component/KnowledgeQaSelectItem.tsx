// @ts-strict-ignore
import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { getKnowledgeDetailApi,readFileLibDatabase } from "@/controllers/API";
import { Select } from "@bisheng/ui";
import { useEffect,useMemo,useRef,useState } from "react";
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
    const selectLabels = useSelectLabels()
    const [value, setValue] = useState<any>(() => data.value.map(el => {
        return { label: el.label, value: el.key }
    }))
    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const cursorRef = useRef<string | null>(null)
    const requestSeqRef = useRef(0)
    const [keyword, setKeyword] = useState('')
    const [loadingMore, setLoadingMore] = useState(false)
    const reload = (cursor: string | null, name: string) => {
        const requestSeq = ++requestSeqRef.current
        setLoadingMore(!!cursor)
        readFileLibDatabase({ cursor, pageSize: PAGE_SIZE, name, type: 1, action: 'use' }).then(res => {
            if (requestSeq !== requestSeqRef.current) return
            cursorRef.current = res.next_cursor
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => cursor ? mergeOptionsByValue(_ops, opts) : opts)
        }).finally(() => {
            if (requestSeq === requestSeqRef.current) setLoadingMore(false)
        })
    }


    useEffect(() => {
        reload(null, '')
    }, [])

    // 加载更多
    const loadMore = (name) => {
        if (cursorRef.current) reload(cursorRef.current, name)
    }

    // Selected items must be known to the Select so their tags keep a label;
    // only merge them into the unfiltered list so a server search stays exact.
    const selectOptions = useMemo(() => {
        const list = keyword ? options : mergeOptionsByValue(options, value)
        return list.filter(option => option.value != null && option.value !== '')
    }, [options, value, keyword])

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
        <Select
            {...selectLabels}
            id="knowledge-qaselect"
            multiple
            // No per-tag error marking in the shared Select: flag the whole field.
            status={error || errorKeys.length ? 'error' : 'default'}
            className="nodrag"
            value={value.map(el => el.value)}
            options={selectOptions}
            placeholder={t(`${i18nPrefix}placeholder`)}
            aria-label={t(`${i18nPrefix}label`)}
            showSearch
            onChange={(_vals, opts) => handleSelect(opts.map(el => ({ label: el.label, value: el.value })))}
            onOpenChange={(open) => { if (open) reload(null, '') }}
            onSearch={(val) => { setKeyword(val); reload(null, val) }}
            onLoadMore={() => loadMore(keyword)}
            loadingMore={loadingMore}
        />
    </div>
};
