import { Badge } from "@/components/bs-ui/badge";
import Parameter from "./Parameter";
import { WorkflowNode } from "@/types/flow";

export default function ParameterGroup({ nodeId, cate, tab, onOutPutChange }
    : { nodeId: string, cate: WorkflowNode['group_params'][number], tab: string, onOutPutChange: (key: string, value: any) => void }) {

    return <div className="px-4 py-2 border-t border-[#E8EAF0]">
        {cate.name && <p className='mt-2 mb-3 text-sm font-bold'>{cate.name}</p>}
        {cate.params.map(item => tab === item.tab || !item.tab ? <Parameter nodeId={nodeId} key={item.key} item={item} onOutPutChange={onOutPutChange} /> : null)}
    </div>
};
