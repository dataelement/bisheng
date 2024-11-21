import { Label } from "@/components/bs-ui/label";
import MultiSelect from "@/components/bs-ui/select/multi";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { readFileLibDatabase } from "@/controllers/API";
import { memo, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../../flowStore";

const TabsHead = memo(({ onChange }) => {

    return <Tabs defaultValue="knowledge" className="mb-2" onValueChange={onChange}>
        <TabsList className="grid w-full grid-cols-2 py-1 max-w-80">
            <TabsTrigger value="knowledge" className="text-xs">文档知识库</TabsTrigger>
            <TabsTrigger value="tmp" className="text-xs">临时会话文件<QuestionTooltip content={'存储用户在当前会话中发送的文件'} /></TabsTrigger>
        </TabsList>
    </Tabs>
})

const enum KnowledgeType {
    Knowledge = 'knowledge',
    Temp = 'tmp'
}
type KnowledgeTypeValues = `${KnowledgeType}`;

export default function KnowledgeSelectItem({ data, onChange, onValidate }) {
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
                                label: val.value,
                                value: val.key
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
        data.required && onValidate(() => {
            if (!data.value.value.length) {
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
            id="knowledge-select-item"
            error={error}
            tabs={<TabsHead onChange={handleTabChange} />}
            multiple
            className={''}
            value={value}
            options={tabType === KnowledgeType.Knowledge ? options : fileOptions}
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
