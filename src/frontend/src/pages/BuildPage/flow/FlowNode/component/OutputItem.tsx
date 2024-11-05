import { Badge } from "@/components/bs-ui/badge";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { useMemo, useState } from "react";
import DragOptions from "./DragOptions";
import VarInput from "./VarInput";
import { Handle, Position } from "@xyflow/react";

const OutputItem = ({ nodeId, data, onChange }) => {
    const [interactionType, setInteractionType] = useState<string>(data.value.type || "none"); // 交互类型状态
    const options = useMemo(() => {
        return data.options.map(el => ({
            id: el.id,
            text: el.label,
            type: ''
        }))
    }, [data])

    // 根据交互类型切换不同的展示
    const renderContent = () => {
        switch (interactionType) {
            case "none":
                return null;
            case "choose":
                return <DragOptions
                    edges
                    options={options}
                    onChange={(opts) => {
                        data.options = opts.map(el => ({
                            id: el.id,
                            label: el.text,
                            value: ''
                        }))
                    }}
                />
            case "input":
                return <div className='node-item mb-2' data-key={data.key}>
                    <div className="flex justify-between items-center">
                        <Label className='bisheng-label'>用户输入框展示内容</Label>
                        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{data.key}</Badge>
                    </div>
                    <VarInput nodeId={nodeId} itemKey={data.key} flowNode={data} value={data.value.value} onChange={(msg) => onChange({ type: interactionType, value: msg })} />
                </div>
            default:
                return null;
        }
    };

    return (
        <div className='node-item mb-4' data-key={data.key}>
            <Label className='bisheng-label'>{data.label}</Label>
            {/* 交互类型选择器 */}
            <RadioGroup value={interactionType} onValueChange={(val) => {
                setInteractionType(val);
                onChange({ type: val, value: '' });
            }} className="mt-2">
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="none" id="r1" />
                    <Label htmlFor="r1">无交互</Label>
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="choose" id="r2" />
                    <Label htmlFor="r2" className="flex items-center">选择型交互
                        <QuestionTooltip content={'提供选项供用户选择，例如在需要进行敏感操作时，需要用户确定方可继续执行工作流'} />
                    </Label>
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="input" id="r3" />
                    <Label htmlFor="r3" className="flex items-center">输入型交互
                        <QuestionTooltip content={'提供用户编辑文本的能力，适合多步任务处理场景，例如用户对模型生成内容直接进行修改，或者输入对生成内容优化意见。用户提交的内容将会存储到 Submitted_Result 变量中。'} />
                    </Label>
                </div>
            </RadioGroup>

            <div className="interaction-content mt-4 nodrag">
                {renderContent()}
                {interactionType !== 'choose' && <Handle
                    id="right_handle"
                    type="source"
                    position={Position.Right}
                    className='bisheng-flow-handle'
                    style={{ right: -16 }}
                />}
            </div>
        </div>
    );
};

export default OutputItem;
