import { WorkflowNodeParam } from "@/types/flow";
import CodeInputItem from "./component/CodeInputItem";
import CodeOutputItem from "./component/CodeOutputItem";
import CodePythonItem from "./component/CodePythonItem";
import ConditionItem from "./component/ConditionItem";
import HistoryNumItem from "./component/HistoryNumItem";
import InputFormItem from "./component/InputFormItem";
import InputItem from "./component/InputItem";
import InputListItem from "./component/InputListItem";
import KnowledgeQaSelectItem from "./component/KnowledgeQaSelectItem";
import KnowledgeSelectItem from "./component/KnowledgeSelectItem";
import ModelItem from "./component/ModelItem";
import OutputItem from "./component/OutputItem";
import ReportItem from "./component/ReportItem";
import SliderItem, { SwitchSliderItem } from "./component/SliderItem";
import SwitchItem from "./component/SwitchItem";
import TextAreaItem from "./component/TextAreaItem";
import ToolItem from "./component/ToolItem";
import VarItem from "./component/VarItem";
import VarSelectItem, { VarSelectSingleItem } from "./component/VarSelectItem";
import VarTextareaItem from "./component/VarTextareaItem";
import VarTextareaUploadItem from "./component/VarTextareaUploadItem";

// 节点表单项
export default function Parameter({ nodeId, item, onOutPutChange, onStatusChange, onVarEvent }
    : {
        nodeId: string,
        item: WorkflowNodeParam,
        onOutPutChange: (key: string, value: any) => void
        onStatusChange: (key: string, obj: any) => void
        onVarEvent: (key: string, obj: any) => void
    }) {

    const handleOnNewValue = (newValue: any, validate?: any) => {
        // 更新by引用(视图更新再组件内部完成)
        item.value = newValue;
        // Set state to pending
    }

    const bindValidate = (validate) => {
        validate && onStatusChange(item.key, { param: item, validate })
    }

    const bindVarValidate = (validate) => {
        onVarEvent(item.key, { param: item, validate })
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
            return <InputFormItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} />
        case 'var_textarea':
            return <VarTextareaItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} onVarEvent={bindVarValidate} />
        case 'var_textarea_file':
            return <VarTextareaUploadItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} onVarEvent={bindVarValidate} />
        case 'output_form':
            return <OutputItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />
        case 'bisheng_model':
            return <ModelItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} />
        case 'slide':
            return <SliderItem data={item} onChange={handleOnNewValue} />
        case 'slide_switch':
            return <SwitchSliderItem data={item} onChange={handleOnNewValue} />
        case 'switch':
            return <SwitchItem data={item} onChange={handleOnNewValue} />;
        case 'var_select':
            return <VarSelectSingleItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'user_question':
            return <VarSelectItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onOutPutChange={onOutPutChange} onValidate={bindValidate} />;
        case 'knowledge_select_multi':
            return <KnowledgeSelectItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'qa_select_multi':
            return <KnowledgeQaSelectItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'number':
            return <InputItem type='number' data={item} onChange={handleOnNewValue} />;
        case 'code_input':
            return <CodeInputItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'code':
            return <CodePythonItem data={item} onChange={handleOnNewValue} />;
        case 'code_output':
            return <CodeOutputItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'add_tool':
            return <ToolItem data={item} onChange={handleOnNewValue} />;
        case 'condition':
            return <ConditionItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'report':
            return <ReportItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        default:
            return <div>Unsupported parameter type</div>;
    }
};
