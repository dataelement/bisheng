import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { getKnowledgeDetailApi, readFileLibDatabase } from "@/controllers/API";
import { getAuthorizedKnowledgeSpaceOptionsApi } from "@/controllers/API/knowledgeSpace";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";
import { buildKnowledgeSpaceGroups, toKnowledgeSpaceOption } from "./knowledgeSpaceSelectUtils";

const TabsHead = memo(({ tab, onChange }) => {
    const { t } = useTranslation('flow');

    return (
        <Tabs defaultValue={tab} className="mb-2" onValueChange={onChange}>
            <TabsList className="grid w-full grid-cols-2 py-1 max-w-80">
                <TabsTrigger value="qa" className="text-xs">
                    {t('node.qa_retriever.qa_knowledge_id.label')}
                </TabsTrigger>
                <TabsTrigger value="space" className="text-xs">
                    {t('knowledgeSpace')}
                </TabsTrigger>
            </TabsList>
        </Tabs>
    );
});

const enum QaKnowledgeType {
    Qa = 'qa',
    Space = 'space'
}
type QaKnowledgeTypeValues = `${QaKnowledgeType}`;
const pageSize = 60
const qaKnowledgeTypes = [QaKnowledgeType.Qa, QaKnowledgeType.Space]

const normalizeQaKnowledgeValue = (rawValue) => {
    if (Array.isArray(rawValue)) {
        return {
            type: QaKnowledgeType.Qa,
            value: rawValue,
        };
    }
    const type = rawValue?.type || QaKnowledgeType.Qa;
    const value = Array.isArray(rawValue?.value) ? rawValue.value : [];
    return {
        type: qaKnowledgeTypes.includes(type) ? type : QaKnowledgeType.Qa,
        value,
    };
};

export default function KnowledgeQaSelectItem({ nodeId, data, onChange, onValidate, onVarEvent, i18nPrefix }) {
    const { t } = useTranslation('flow')
    const { flow } = useFlowStore()
    const initialValue = normalizeQaKnowledgeValue(data.value);
    const currentTabRef = useRef(initialValue.type)
    const [tabType, setTabType] = useState<QaKnowledgeTypeValues>(initialValue.type)
    const [value, setValue] = useState<any>(() => initialValue.value.map(el => {
        return { label: el.label, value: el.key }
    }))
    const [options, setOptions] = useState<any>([]);
    const [spaceOptions, setSpaceOptions] = useState<any>([]);
    const originOptionsRef = useRef([])

    const qaCursorRef = useRef<string | null>(null)
    const qaHasMoreRef = useRef(true)
    const spacePageRef = useRef(1)
    const spaceHasMoreRef = useRef(true)
    const spaceLoadingRef = useRef(false)
    const spaceRequestIdRef = useRef(0)
    const [spaceLoading, setSpaceLoading] = useState(false)

    const reloadQaKnowledge = (reset = true, name = '') => {
        if (!reset && !qaHasMoreRef.current) return
        readFileLibDatabase({
            cursor: reset ? null : qaCursorRef.current,
            pageSize,
            name,
            type: 1,
            permissionId: 'use_kb'
        }).then(res => {
            originOptionsRef.current = res.data
            const opts = res.data.map(el => ({ label: el.name, value: el.id }))
            setOptions(_ops => reset ? opts : [..._ops, ...opts])
            qaCursorRef.current = res.next_cursor
            qaHasMoreRef.current = Boolean(res.has_more)
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

    useEffect(() => {
        reloadQaKnowledge(true, '')
        reloadSpaces(1, '')
    }, [])

    // Load more
    const loadMore = (name) => {
        if (tabType === QaKnowledgeType.Qa) {
            reloadQaKnowledge(false, name)
            return
        }
        reloadSpaces(spacePageRef.current + 1, name)
    }

    const handleTabChange = (val) => {
        if (QaKnowledgeType.Qa === val) {
            reloadQaKnowledge(true, '')
        } else {
            reloadSpaces(1, '')
        }
        setTabType(val)
        const inputDom = document.getElementById('knowledge-qaselect') as HTMLInputElement
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

    const handleSelect = (resVals) => {
        if (!resVals.length) {
            setValue([])
            onChange({
                type: tabType,
                value: []
            })
            currentTabRef.current = tabType
            return
        }
        const scopedVals = currentTabRef.current === tabType ? resVals : [resVals[resVals.length - 1]]
        setValue(scopedVals)
        onChange({
            type: tabType,
            value: scopedVals.map(el => ({
                key: el.value,
                label: el.label
            }))
        })
        currentTabRef.current = tabType
    }

    const handleLoad = () => {
        if (tabType === QaKnowledgeType.Qa) {
            reloadQaKnowledge(true, '')
        } else {
            reloadSpaces(1, '')
        }
    }

    const handleSearch = (val) => {
        if (tabType === QaKnowledgeType.Qa) {
            reloadQaKnowledge(true, val)
        } else {
            reloadSpaces(1, val)
        }
    }
    const spaceGroups = tabType === QaKnowledgeType.Space ? buildKnowledgeSpaceGroups(spaceOptions, t) : []

    const [error, setError] = useState(false)
    useEffect(() => {
        data.required && onValidate(() => {
            const normalizedValue = normalizeQaKnowledgeValue(data.value);
            if (!normalizedValue.value.length) {
                setError(true)
                return t(`${i18nPrefix}label`) + ' ' + t('required')
            }
            if (normalizedValue.value.some(item => /input_[a-zA-Z0-9]+\.file/.test(item.key))) {
                return 'input_file'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { })
    }, [data.value])

    // Validate selected knowledge availability
    const [errorKeys, setErrorKeys] = useState<string[]>([])
    const validateVarAvailble = async () => {
        if (!value.length) return ''
        let error = '';
        const _errorKeys = [];
        if (normalizeQaKnowledgeValue(data.value).type === QaKnowledgeType.Space) {
            setErrorKeys([]);
            return '';
        }
        const effectiveKnowledges = await getKnowledgeDetailApi(value.map(el => el.value));
        for (const el of value) {
            if (!effectiveKnowledges.some(base => base.id === el.value)) {
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
            tabs={<TabsHead tab={tabType} onChange={handleTabChange} />}
            multiple
            className={''}
            value={value}
            options={tabType === QaKnowledgeType.Qa ? options : spaceOptions}
            groupedOptions={spaceGroups}
            loading={tabType === QaKnowledgeType.Space && spaceLoading}
            loadingText={t('loadingKnowledgeSpaces')}
            emptyText={tabType === QaKnowledgeType.Space ? t('emptyKnowledgeSpaces') : ''}
            placeholder={t(`${i18nPrefix}placeholder`)}
            searchPlaceholder={tabType === QaKnowledgeType.Space ? t('searchKnowledgeSpaceName') : t('build.searchBaseName', { ns: 'bs' })}
            onChange={handleSelect}
            onLoad={handleLoad}
            onSearch={handleSearch}
            onScrollLoad={(val) => loadMore(val)}
        >
            {/* {children?.(reload)} */}
        </MultiSelect>
    </div>
};
