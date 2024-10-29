import { WorkflowNodeParam } from "@/types/flow";
import HistoryNumItem from "./component/HistoryNumItem";
import InputFormItem from "./component/InputFormItem";
import InputItem from "./component/InputItem";
import InputListItem from "./component/InputListItem";
import KnowledgeSelectItem from "./component/KnowledgeSelectItem";
import ModelItem from "./component/ModelItem";
import OutputItem from "./component/OutputItem";
import SliderItem from "./component/SliderItem";
import SwitchItem from "./component/SwitchItem";
import TextAreaItem from "./component/TextAreaItem";
import VarItem from "./component/VarItem";
import VarSelectItem from "./component/VarSelectItem";
import VarTextareaItem from "./component/VarTextareaItem";
import VarTextareaUploadItem from "./component/VarTextareaUploadItem";

// 节点表单项
export default function Parameter({ nodeId, item, onOutPutChange }
    : { nodeId: string, item: WorkflowNodeParam, onOutPutChange: (key: string, value: any) => void }) {

    const handleOnNewValue = (newValue: any) => {
        // 更新by引用(视图更新再组件内部完成)
        item.value = newValue;
        // Set state to pending
    }

    // 渲染逻辑根据 `type` 返回不同的组件
    switch (item.type) {
        case 'textarea':
            return <TextAreaItem data={item} onChange={handleOnNewValue} />;
        case 'input':
            return <InputItem data={item} onChange={handleOnNewValue} />;
        case 'input_list':
            return <InputListItem data={item} onChange={handleOnNewValue} />;
        case 'var':
            return <VarItem data={item} />
        case 'chat_history_num':
            return <HistoryNumItem data={item} onChange={handleOnNewValue} />
        case 'form':
            return <InputFormItem data={item} onChange={handleOnNewValue} />
        case 'var_textarea_file':
            return <VarTextareaUploadItem nodeId={nodeId} data={item} onChange={handleOnNewValue} />
        case 'output_form':
            return <OutputItem nodeId={nodeId} data={item} onChange={handleOnNewValue} />
        case 'bisheng_model':
            return <ModelItem data={item} onChange={handleOnNewValue} />
        case 'slide':
            return <SliderItem data={item} onChange={handleOnNewValue} />
        case 'var_textarea':
            return <VarTextareaItem nodeId={nodeId} data={item} onChange={handleOnNewValue} />
        case 'switch':
            return <SwitchItem data={item} onChange={handleOnNewValue} />;
        case 'user_question':
            return <VarSelectItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onOutPutChange={onOutPutChange} />;
        case 'knowledge_select_multi':
            return <KnowledgeSelectItem data={item} onChange={handleOnNewValue} />;
        case 'number':
            return <InputItem type='number' data={item} onChange={handleOnNewValue} />;
        // case 'date':
        //     return <DateParameter />;
        // case 'boolean':
        //     return <BooleanParameter />;
        default:
            return <div>Unsupported parameter type</div>;
    }
};
