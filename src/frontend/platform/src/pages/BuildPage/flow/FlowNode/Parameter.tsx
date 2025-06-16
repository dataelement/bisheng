import { WorkflowNode, WorkflowNodeParam } from "@/types/flow";
import CodeInputItem from "./component/CodeInputItem";
import CodeOutputItem from "./component/CodeOutputItem";
import CodePythonItem from "./component/CodePythonItem";
import ConditionItem from "./component/ConditionItem";
import FileTypeSelect from "./component/FileTypeSelect";
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
import SqlConfigItem from "./component/SqlConfigItem";
import SwitchItem from "./component/SwitchItem";
import TextAreaItem from "./component/TextAreaItem";
import ToolItem from "./component/ToolItem";
import VarItem from "./component/VarItem";
import VarSelectItem, { VarSelectSingleItem } from "./component/VarSelectItem";
import VarTextareaItem from "./component/VarTextareaItem";
import VarTextareaUploadItem from "./component/VarTextareaUploadItem";
import ImagePromptItem from "./component/ImagePromptItem";
import OnlineSwitchItem from "./component/onlineSwitchItem";

// 节点表单项
export default function Parameter({ node, nodeId, item, onOutPutChange, onStatusChange, onFouceUpdate, onVarEvent }
    : {
        nodeId: string,
        node: WorkflowNode,
        item: WorkflowNodeParam,
        onOutPutChange: (key: string, value: any) => void
        onStatusChange: (key: string, obj: any) => void
        onVarEvent: (key: string, obj: any) => void
        onFouceUpdate: () => void
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

    if (item.hidden) return null

    // 渲染逻辑根据 `type` 返回不同的组件
    switch (item.type) {
        case 'textarea':
            return <TextAreaItem data={item} onChange={handleOnNewValue} />;
        case 'input':
            return <InputItem data={item} onChange={handleOnNewValue} />;
        case 'input_list':
            return <InputListItem data={item} dict={item.key === "preset_question"} onChange={handleOnNewValue} />;
        case 'var':
            return <VarItem data={item} />
        case 'chat_history_num':
            return <HistoryNumItem data={item} onChange={handleOnNewValue} />
        case 'form':
            return <InputFormItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} onVarEvent={bindVarValidate} />
        case 'var_textarea':
            return <VarTextareaItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} onVarEvent={bindVarValidate} />
        case 'var_textarea_file':
            return <VarTextareaUploadItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} onVarEvent={bindVarValidate} />
        case 'output_form':
            return <OutputItem nodeId={nodeId} node={node} data={item} onChange={handleOnNewValue} onValidate={bindValidate} onVarEvent={bindVarValidate} />
        case 'bisheng_model':
            return <ModelItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} type='model' />
        case 'agent_model':
            return <ModelItem agent data={item} onChange={handleOnNewValue} onValidate={bindValidate} type='agentModel' />
        case 'tts_model':
            return <ModelItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} type='tts' />
        case 'stt_model':
            return <ModelItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} type='stt' />
        case 'slide':
            return <SliderItem data={item} onChange={handleOnNewValue} />
        case 'slide_switch':
            return <SwitchSliderItem data={item} onChange={handleOnNewValue} />
        case 'switch':
            return <SwitchItem data={item} onChange={handleOnNewValue} />;
        case 'online_switch':
            return <OnlineSwitchItem data={item} onChange={handleOnNewValue}  node={node} item={item} />;
        case 'var_select':
            return <VarSelectSingleItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate} />;
        case 'user_question':
            return <VarSelectItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onOutPutChange={onOutPutChange}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate} />;
        case 'knowledge_select_multi':
            return <KnowledgeSelectItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
            />;
        case 'qa_select_multi':
            return <KnowledgeQaSelectItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
            />;
        case 'number':
            return <InputItem type='number' data={item} onChange={handleOnNewValue} />;
        case 'char_number':
            return <InputItem char type='number' data={item} onChange={handleOnNewValue} />;
        case 'code_input':
            return <CodeInputItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'code':
            return <CodePythonItem data={item} onChange={handleOnNewValue} />;
        case 'code_output':
            return <CodeOutputItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'add_tool':
            return <ToolItem data={item} onChange={handleOnNewValue} />;
        case 'condition':
            return <ConditionItem
                nodeId={nodeId}
                node={node}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
            />;
        case 'report':
            return <ReportItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'sql_config':
            return <SqlConfigItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} />;
        case 'select_fileaccept':
            return <FileTypeSelect data={item} onChange={(val) => {
                // group_params[0] 受input模板影响
                const imageFileItem = node.group_params[0].params.find(param => {
                    if (param.key === 'dialog_image_files') return true
                })
                imageFileItem.hidden = val === 'file'
                handleOnNewValue(val)
                onFouceUpdate()
            }} />;
        case 'image_prompt':
            return <ImagePromptItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onVarEvent={bindVarValidate} />;
        default:
            return <div>Unsupported parameter type</div>;
    }
};
