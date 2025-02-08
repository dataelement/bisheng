import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getKnowledgeDetailApi, readFileLibDatabase } from "@/controllers/API";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";


export default function KnowledgeQaSelectItem({ nodeId, data, onChange, onValidate, onVarEvent }) {
    const { t } = useTranslation()
    const { flow } = useFlowStore()
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
                return data.label + ' ' + t('required')
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
                error = t('nodeErrorMessage', {
                    ns: 'flow',
                    nodeName: flow.nodes.find(node => node.id === nodeId).data.name,
                    varNameCn: ''
                });
            }
            error && _errorKeys.push(el.value);
            setErrorKeys(_errorKeys);
            return error;
        }
    };
    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailble);
        return () => onVarEvent && onVarEvent(() => { });
    }, [data, value]);

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}
            {data.label}
        </Label>
        <MultiSelect
            id="knowledge-qaselect"
            error={error}
            errorKeys={errorKeys}
            multiple
            className={''}
            value={value}
            options={options}
            placeholder={data.placeholder}
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
