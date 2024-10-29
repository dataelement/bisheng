import { Badge } from "@/components/bs-ui/badge";
import Parameter from "./Parameter";
import { WorkflowNode } from "@/types/flow";

export default function ParameterGroup({ nodeId, cate, tab, onOutPutChange }
    : { nodeId: string, cate: WorkflowNode['group_params'][number], tab: string, onOutPutChange: (key: string, value: any) => void }) {

    return <div className="px-4 pb-4 border-b-8 border-background">
        {cate.name && <Badge className='my-2'>{cate.name}</Badge>}
        {cate.params.map(item => tab === item.tab || !item.tab ? <Parameter nodeId={nodeId} key={item.key} item={item} onOutPutChange={onOutPutChange} /> : null)}
    </div>
};
