import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getKnowledgeDetailApi, readFileLibDatabase } from "@/controllers/API";
import { getAuthorizedKnowledgeSpaceOptionsApi } from "@/controllers/API/knowledgeSpace";
import { isVarInFlow } from "@/util/flowUtils";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import { buildKnowledgeSpaceGroups, toKnowledgeSpaceOption } from "./knowledgeSpaceSelectUtils";


const TabsHead = memo(({ tab, onChange }) => {
    const { t } = useTranslation('flow');

    return (
        <Tabs defaultValue={tab} className="mb-2" onValueChange={onChange}>
            <TabsList className="grid w-full grid-cols-3 py-1 max-w-80">
                <TabsTrigger value="knowledge" className="text-xs">
                    {t('documentKnowledgeBase')}
                </TabsTrigger>
                <TabsTrigger value="space" className="text-xs">
                    {t('knowledgeSpace')}
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
    Space = 'space',
    Temp = 'tmp'
}
type KnowledgeTypeValues = `${KnowledgeType}`;
const pageSize = 60
const knowledgeTypes = [KnowledgeType.Knowledge, KnowledgeType.Space, KnowledgeType.Temp]

const normalizeKnowledgeValue = (rawValue) => {
    const type = rawValue?.type || KnowledgeType.Knowledge;
    const value = Array.isArray(rawValue?.value) ? rawValue.value : [];
    return {
        type: knowledgeTypes.includes(type) ? type : KnowledgeType.Knowledge,
        value,
    };
};

export default function KnowledgeSelectItem({ data, nodeId, onChange, onVarEvent, onValidate, i18nPrefix }) {
    const { flow } = useFlowStore()
    const { t } = useTranslation('flow')

    const initialValue = normalizeKnowledgeValue(data.value);
    const currentTabRef = useRef(initialValue.type)
    const [tabType, setTabType] = useState<KnowledgeTypeValues>(initialValue.type)
    const [value, setValue] = useState<any>(() => initialValue.value.map(el => {
        return { label: el.label, value: el.key }
    }))

    const [options, setOptions] = useState<any>([]);
    const [spaceOptions, setSpaceOptions] = useState<any>([]);
    const [fileOptions, setFileOptions] = useState<any>([])
    const originOptionsRef = useRef([])

    const knowledgeCursorRef = useRef<string | null>(null)
    const knowledgeHasMoreRef = useRef(true)
    const spacePageRef = useRef(1)
    const spaceHasMoreRef = useRef(true)
    const spaceLoadingRef = useRef(false)
    const spaceRequestIdRef = useRef(0)
    const [spaceLoading, setSpaceLoading] = useState(false)

    const reloadKnowledge = (reset = true, name = '') => {
        if (!reset && !knowledgeHasMoreRef.current) return
        readFileLibDatabase({
            cursor: reset ? null : knowledgeCursorRef.current,
            pageSize,
            name,
            type: 0,
            permissionId: 'use_kb'
        }).then(res => {
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => reset ? opts : [..._ops, ...opts])
            knowledgeCursorRef.current = res.next_cursor
            knowledgeHasMoreRef.current = Boolean(res.has_more)
        })
    }

    const reloadSpaces = (page, keyword) => {
        if (page > 1 && (spaceLoadingRef.current || !spaceHasMoreRef.current)) return
        const requestId = ++spaceRequestIdRef.current
        if (page === 1) {
            setSpaceOptions([])
            spaceHasMoreRef.current = true
        }
        spaceLoadingRef.current = true
        setSpaceLoading(true)
        getAuthorizedKnowledgeSpaceOptionsApi({
            page,
            page_size: pageSize,
            keyword,
            order_by: 'name',
        }).then(res => {
            if (requestId !== spaceRequestIdRef.current) return
            spacePageRef.current = page
            const opts = res.data.map(toKnowledgeSpaceOption)
            setSpaceOptions(_ops => page > 1 ? [..._ops, ...opts] : opts)
            spaceHasMoreRef.current = Boolean(res.has_more)
        }).catch(() => {
            if (requestId === spaceRequestIdRef.current && page === 1) {
                setSpaceOptions([])
                spaceHasMoreRef.current = false
            }
        }).finally(() => {
            if (requestId === spaceRequestIdRef.current) {
                spaceLoadingRef.current = false
                setSpaceLoading(false)
            }
        })
    }
    // input文件变量s
    const loadFiles = () => {
        const files = []
        flow.nodes.forEach(node => {
            if (node.data.type !== 'input') return
            if (node.data.tab.value === "dialog_input") return
            node.data.group_params.forEach(group => {
                group.params.forEach(param => {
                    if (param.key === 'form_input') {
                        param.value.forEach(val => {
                            val.file_parse_mode === 'ingest_to_temp_kb' && val.type === 'file'
                                && files.push({
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
        reloadKnowledge(true, '')
        reloadSpaces(1, '')
        loadFiles()
    }, [])

    // const handleChange = (res) => {
    //     // id => obj
    //     onChange(res.map(el => originOptionsRef.current.find(el2 => el2.id === el)))
    // }

    // 加载更多
    const loadMore = (name) => {
        if (tabType === KnowledgeType.Knowledge) {
            reloadKnowledge(false, name)
            return
        }
        if (tabType === KnowledgeType.Space) {
            reloadSpaces(spacePageRef.current + 1, name)
        }
    }

    const handleTabChange = (val) => {
        if (KnowledgeType.Knowledge === val) {
            reloadKnowledge(true, '')
        } else if (KnowledgeType.Space === val) {
            reloadSpaces(1, '')
        } else {
            loadFiles()
        }

        setTabType(val)
        const inputDom = document.getElementById('knowledge-select-item')
        if (inputDom) {
            inputDom.value = ''
        }
        setValue([])
        onChange({
            type: val,
            value: []
        })
        currentTabRef.current = val
    }

    const handleSelect = (vals) => {
        if (!vals.length) {
            setValue([])
            onChange({
                type: tabType,
                value: []
            })
            currentTabRef.current = tabType
            return
        }
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

    const handleLoad = () => {
        if (tabType === KnowledgeType.Knowledge) {
            reloadKnowledge(true, '')
        } else if (tabType === KnowledgeType.Space) {
            reloadSpaces(1, '')
        } else {
            loadFiles()
        }
    }

    const handleSearch = (val) => {
        if (tabType === KnowledgeType.Knowledge) {
            reloadKnowledge(true, val)
        } else if (tabType === KnowledgeType.Space) {
            reloadSpaces(1, val)
        }
    }

    const selectOptions = tabType === KnowledgeType.Knowledge
        ? options
        : tabType === KnowledgeType.Space
            ? spaceOptions
            : fileOptions
    const spaceGroups = tabType === KnowledgeType.Space ? buildKnowledgeSpaceGroups(spaceOptions, t) : []

    const [error, setError] = useState(false)
    useEffect(() => {
        // data.required && onValidate(() => {
        onValidate((config) => {
            const normalizedValue = normalizeKnowledgeValue(data.value);
            if (data.required && !normalizedValue.value.length) {
                setError(true)
                return `${t(`${i18nPrefix}label`)} ${t('required')}`;
            }
            if (normalizedValue.value.some(item => /input_[a-zA-Z0-9]+\.file/.test(item.key))) {
                return 'input_file'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { })
    }, [data.value])

    // 校验变量是否可用
    const [errorKeys, setErrorKeys] = useState<string[]>([])
    const validateVarAvailable = async (config) => {
        if (!value.length) return ''
        let error = '';
        // 单节点运行校验临时文件
        const normalizedValue = normalizeKnowledgeValue(data.value);
        if (config?.tmp && normalizedValue.value.length && normalizedValue.type === KnowledgeType.Temp) {
            setError(true)
            return t('tmpKnowledgeBaseNotSupportSingleNodeDebug')
        }
        if (normalizedValue.type === KnowledgeType.Space) {
            setErrorKeys([]);
            return '';
        }
        const _errorKeys = [];
        if (normalizedValue.type === KnowledgeType.Knowledge && typeof value[0].value === 'number') {
            const effectiveKnowledges = await getKnowledgeDetailApi(value.map(el => el.value));
            for (const el of value) {
                // If not found, check against effectiveKnowledges
                if (!effectiveKnowledges.some(base => base.id === el.value)) {
                    // error = t('nodeErrorMessage', {
                    //     ns: 'flow',
                    //     nodeName: flow.nodes.find(node => node.id === nodeId).data.name,
                    //     varNameCn: ''
                    // });
                    error = `${flow.nodes.find(node => node.id === nodeId).data.name}${t('nodeError')}: ${el.label} ${t('doesNotExist')}.`
                    error && _errorKeys.push(el.value);
                }
                setErrorKeys(_errorKeys);
            }
            return error;
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
            {t(`${i18nPrefix}label`)}
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
            options={selectOptions}
            groupedOptions={spaceGroups}
            loading={tabType === KnowledgeType.Space && spaceLoading}
            loadingText={t('loadingKnowledgeSpaces')}
            emptyText={tabType === KnowledgeType.Space ? t('emptyKnowledgeSpaces') : ''}
            placeholder={data.placeholder && t(`${i18nPrefix}placeholder`) || ''}
            searchPlaceholder={tabType === KnowledgeType.Space ? t('searchKnowledgeSpaceName') : t('build.searchBaseName', { ns: 'bs' })}
            onChange={handleSelect}
            onLoad={handleLoad}
            onSearch={handleSearch}
            onScrollLoad={(val) => loadMore(val)}
        >
            {/* {children?.(reload)} */}
        </MultiSelect>
    </div>
};
