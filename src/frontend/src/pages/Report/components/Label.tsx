import { Braces } from "lucide-react";
import { useContext, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Input } from "../../../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../../../components/ui/select1";
import { TabsContext } from "../../../contexts/tabsContext";
import { useDebounce } from "../../../util/hook";
import { getVariablesApi } from "../../../controllers/API/flow";
import { useTranslation } from "react-i18next";

export default function Label({ onInset }) {
    const { id: flowId } = useParams();
    const { flows } = useContext(TabsContext);

    const nodes = useMemo(() => {
        const _flow = flows.find(flow => flow.id === flowId);
        if (!_flow) return [];
        // 提取报表变量
        return _flow.data.nodes.reduce((res, node) => {
            if (["InputNode", "VariableNode", "UniversalKVLoader", "CustomKVLoader"].includes(node.data.type)) {
                res.push({
                    id: node.id,
                    nodeName: node.data.type,
                    node: node.data.node
                })
            }
            return res
        }, [])
    }, [flows, flowId])

    // labels
    const { selectChange, labels, onSearch } = useLabels(flowId, nodes)
    const { t } = useTranslation()

    return <div className="flex flex-col gap-4">
        {/* Select component */}
        <Select onValueChange={selectChange}>
            <SelectTrigger className="">
                <SelectValue placeholder={t('report.selectComponent')} />
            </SelectTrigger>
            <SelectContent className="">
                <SelectGroup>
                    {nodes.map((node, i) => {
                        return <SelectItem key={node.id} value={String(i)}>{node.id}</SelectItem>
                    })}
                </SelectGroup>
            </SelectContent>
        </Select>
        {/* 搜索框 */}
        <Input placeholder="Search..." onChange={onSearch}></Input>
        {/* 变量 */}
        <div className="h-full">
            {labels.map(label =>
                <div
                    key={label.label}
                    onClick={() => onInset(label.value)}
                    className="flex items-center gap-2 pl-2 py-2 text-[#8285a6] cursor-pointer hover:bg-gray-100 rounded-sm text-sm"
                ><Braces size={16} className="min-w-[20px]" /><span className="truncate">{label.label}</span></div>
            )}
        </div>
    </div>
};


const useLabels = (flowId, nodes) => {
    // 变量列表
    const [labels, setLabels] = useState([])
    const [keyWord, setKeyWord] = useState([])
    const handleSelect = (index) => {
        const { id, nodeName, node } = nodes[Number(index)];
        // inputnode 提取 变量
        if (nodeName === "InputNode") {
            return setLabels(node.template.input.value.map(el => ({
                label: el, value: `${id}_${el}`
            })))
        }
        // UniversalKVLoader 提取 变量
        if (nodeName === "UniversalKVLoader") {
            const schema = node.template.schema.value
            if (!schema) return setLabels([])
            return setLabels(schema.split('|').map(el => {
                return { label: el, value: `${id}_${el}` }
            }))
        }
        // CustomKVLoader 提取 变量
        if (nodeName === "CustomKVLoader") {
            const schemas = node.template.schemas.value || ''
            if (!schemas) return setLabels([])
            return setLabels(schemas.split('|').map(el => {
                return { label: el, value: `${id}_${el}` }
            }))
        }
        // api
        // Variable 提取 变量
        getVariablesApi({
            flow_id: flowId,
            node_id: id
        }).then(arr => {
            setLabels(arr.map(item => {
                return {
                    label: item.name,
                    value: `${id}_${item.name}`
                }
            }))
        })
    }

    const showLabels = useMemo(() =>
        labels.filter(label => label.label.includes(keyWord))
        , [labels, keyWord])

    const handleSearch = useDebounce((e) => {
        setKeyWord(e.target.value)
    }, 500, false)

    return {
        selectChange: handleSelect,
        onSearch: handleSearch,
        labels: showLabels
    }
}
