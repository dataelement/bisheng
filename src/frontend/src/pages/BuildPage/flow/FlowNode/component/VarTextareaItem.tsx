import { Label } from "@/components/bs-ui/label";
import VarInput from "./VarInput";

export default function VarTextareaItem({ nodeId, data, onChange }) {

    return (
        <div className='node-item mb-2 nodrag' data-key={data.key}>
            <Label className='bisheng-label'>{data.label}</Label>
            <VarInput
                nodeId={nodeId}
                flowNode={data}
                value={data.value}
                onChange={onChange}
            >
            </VarInput>
        </div>
    );
}
