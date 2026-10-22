// @ts-strict-ignore
import { Input, Select } from '@bisheng/ui';
import { Braces } from "lucide-react";
import { useContext, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { TabsContext } from "../../../contexts/tabsContext";
import { getVariablesApi } from "../../../controllers/API/flow";
import { useDebounce } from "../../../util/hook";

export default function Label({ onInset }) {
    const { id: flowId } = useParams();
    const { flow } = useContext(TabsContext);

    const nodes = useMemo(() => {
        if (!flow) return [];

        return flow.data.nodes.reduce((res, node) => {
            if (["InputNode", "VariableNode", "UniversalKVLoader", "CustomKVLoader"].includes(node.data.type)) {
                res.push({
                    id: node.id,
                    nodeName: node.data.type,
                    node: node.data.node,
                });
            }
            return res;
        }, []);
    }, [flow]);

    // labels
    const { selectChange, labels, onSearch } = useLabels(flowId, nodes);
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();

    return (
        <div className="flex flex-col gap-4">
            {/* Select component */}
            <Select
                {...selectLabels}
                options={nodes.map((node, i) => ({ value: String(i), label: node.id }))}
                onChange={(v) => { if (v != null) selectChange(v) }}
                placeholder={t("report.selectComponent")}
                aria-label={t("report.selectComponent")}
            />
            {}
            <Input placeholder="Search..." onChange={onSearch}></Input>
            {}
            <div className="h-full">
                {labels.map((label) => (
                    <div
                        key={label.label}
                        onClick={() => onInset(label.value)}
                        className="flex items-center gap-2 pl-2 py-2 text-[#8285a6] cursor-pointer hover:bg-gray-100 rounded-sm text-sm"
                    >
                        <Braces size={16} className="min-w-[20px]" />
                        <span className="truncate">{label.label}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

const useLabels = (flowId, nodes) => {
    const [labels, setLabels] = useState([]);
    const [keyWord, setKeyWord] = useState([]);
    const handleSelect = (index) => {
        const { id, nodeName, node } = nodes[Number(index)];

        if (nodeName === "InputNode") {
            return setLabels(
                node.template.input.value.map((el) => ({
                    label: el,
                    value: `${id}_${el}`,
                })),
            );
        }
        // UniversalKVLoader 提取 变量
        if (nodeName === "UniversalKVLoader") {
            const schema = node.template.schema.value;
            if (!schema) return setLabels([]);
            return setLabels(
                schema.split("|").map((el) => {
                    return { label: el, value: `${id}_${el}` };
                }),
            );
        }
        // CustomKVLoader 提取 变量
        if (nodeName === "CustomKVLoader") {
            const schemas = node.template.schemas.value || "";
            if (!schemas) return setLabels([]);
            return setLabels(
                schemas.split("|").map((el) => {
                    return { label: el, value: `${id}_${el}` };
                }),
            );
        }
        // api
        // Variable 提取 变量
        getVariablesApi({
            flow_id: flowId,
            node_id: id,
        }).then((arr) => {
            setLabels(
                arr.map((item) => {
                    return {
                        label: item.name,
                        value: `${id}_${item.name}`,
                    };
                }),
            );
        });
    };

    const showLabels = useMemo(() => labels.filter((label) => label.label.includes(keyWord)), [labels, keyWord]);

    const handleSearch = useDebounce(
        (e) => {
            setKeyWord(e.target.value);
        },
        500,
        false,
    );

    return {
        selectChange: handleSelect,
        onSearch: handleSearch,
        labels: showLabels,
    };
};
