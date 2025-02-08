import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getKnowledgeDetailApi, readFileLibDatabase } from "@/controllers/API";
import { isVarInFlow } from "@/util/flowUtils";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";


const TabsHead = memo(({ tab, onChange }) => {
    const { t } = useTranslation('flow');

    return (
        <Tabs defaultValue={tab} className="mb-2" onValueChange={onChange}>
            <TabsList className="grid w-full grid-cols-2 py-1 max-w-80">
                <TabsTrigger value="knowledge" className="text-xs">
                    {t('documentKnowledgeBase')}
                </TabsTrigger>
                <TabsTrigger value="tmp" className="text-xs">
                    {t('temporarySessionFiles')}
                    <QuestionTooltip content={t('storeFilesSentInCurrentSession')} />
                </TabsTrigger>
            </TabsList>
        </Tabs>
    );
});


const enum KnowledgeType {
    Knowledge = 'knowledge',
    Temp = 'tmp'
}
type KnowledgeTypeValues = `${KnowledgeType}`;

export default function KnowledgeSelectItem({ data, nodeId, onChange, onVarEvent, onValidate }) {
    const { flow } = useFlowStore()

    const currentTabRef = useRef(data.value.type)
    const [tabType, setTabType] = useState<KnowledgeTypeValues>(data.value.type)
    const [value, setValue] = useState<any>(() => data.value.value.map(el => {
        return { label: el.label, value: el.key }
    }))

    const { t } = useTranslation()
    const [options, setOptions] = useState<any>([]);
    const [fileOptions, setFileOptions] = useState<any>([])
    const originOptionsRef = useRef([])

    const pageRef = useRef(1)
    const reload = (page, name) => {
        readFileLibDatabase({ page, pageSize: 60, name, type: 0 }).then(res => {
            pageRef.current = page
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => page > 1 ? [..._ops, ...opts] : opts)
        })
    }
    // input文件变量s
    const loadFiles = () => {
        const files = []
        flow.nodes.forEach(node => {
            if (node.data.type !== 'input') return
            node.data.group_params.forEach(group => {
                group.params.forEach(param => {
                    if (param.key === 'form_input') {
                        param.value.forEach(val => {
                            val.type === 'file' && files.push({
                                label: `${val.key}(${val.value})`,
                                value: `${node.id}.${val.key}`
                            })
                        })
                    }
                })
            })
        })
        setFileOptions(files)
    }

    useEffect(() => {
        reload(1, '')
        loadFiles()
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
        KnowledgeType.Knowledge === val ? reload(1, '') : loadFiles()

        setTabType(val)
        const inputDom = document.getElementById('knowledge-select-item')
        if (inputDom) {
            inputDom.value = ''
        }
    }

    const handleSelect = (vals) => {
        const resVals = currentTabRef.current === tabType ? vals : [vals[vals.length - 1]]
        setValue(resVals)
        onChange({
            type: tabType,
            value: resVals.map(el => ({ // 夸类型先清空value
                key: el.value,
                label: el.label
            }))
        })

        currentTabRef.current = tabType
    }

    const [error, setError] = useState(false)
    useEffect(() => {
        // data.required && onValidate(() => {
        onValidate(() => {
            if (!data.value.value.length) {
                setError(true)
                return data.label + ' ' + t('required')
            }
            if (data.value.value.some(item => /input_[a-zA-Z0-9]+\.file/.test(item.key))) {
                return 'input_file'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { })
    }, [data.value])

    // 校验变量是否可用
    const [errorKeys, setErrorKeys] = useState<string[]>([])
    const validateVarAvailable = async () => {
        if (!value.length) return ''
        let error = '';
        const _errorKeys = [];
        if (typeof value[0].value === 'number') {
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
        }
        for (const el of value) {
            // Check if variable exists in flow
            let _error = isVarInFlow(nodeId, flow.nodes, el.value, '');
            if (_error) {
                _errorKeys.push(el.value);
                error = _error;
            }
        }
        setErrorKeys(_errorKeys);
        return error;
    };

    useEffect(() => {
        onVarEvent && onVarEvent(validateVarAvailable);
        return () => onVarEvent && onVarEvent(() => { });
    }, [data, value]);

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}
            {data.label}
        </Label>
        <MultiSelect
            id="knowledge-select-item"
            error={error}
            errorKeys={errorKeys}
            tabs={<TabsHead tab={tabType} onChange={handleTabChange} />}
            multiple
            className={''}
            hideSearch={tabType === KnowledgeType.Temp}
            value={value}
            options={tabType === KnowledgeType.Knowledge ? options : fileOptions}
            placeholder={data.placeholder || ''}
            searchPlaceholder={t('build.searchBaseName')}
            onChange={handleSelect}
            onLoad={() => { reload(1, ''); loadFiles() }}
            onSearch={(val) => reload(1, val)}
            onScrollLoad={(val) => loadMore(val)}
        >
            {/* {children?.(reload)} */}
        </MultiSelect>
    </div>
};
