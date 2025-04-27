import { WorkflowNode } from "@/types/flow";
import Parameter from "./Parameter";

export default function ParameterGroup({ nodeId, node, cate, tab, onOutPutChange, onStatusChange, onVarEvent, onFouceUpdate }
    : {
        nodeId: string,
        node: WorkflowNode,
        cate: WorkflowNode['group_params'][number],
        tab: string,
        onOutPutChange: (key: string, value: any) => void
        onStatusChange: (key: string, obj: any) => void
        onVarEvent: (key: string, obj: any) => void
        onFouceUpdate: () => void
    }) {

    if (!cate.params.filter(el => tab === el.tab || !el.tab).length) return null

    return <div className="px-4 py-2 border-t border-[#E8EAF0] dark:border-gray-700">
        {cate.name && <p className='mt-2 mb-3 text-sm font-bold'>{cate.name}</p>}
        {cate.params.map(item => tab === item.tab || !item.tab ? <Parameter
            nodeId={nodeId}
            node={node}
            key={item.key}
            item={item}
            onOutPutChange={onOutPutChange}
            onStatusChange={onStatusChange}
            onVarEvent={onVarEvent}
            onFouceUpdate={onFouceUpdate}
        /> : null)}
    </div>
};
