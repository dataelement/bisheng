import { WorkflowNode, WorkflowNodeParam } from "@/types/flow";
import CodeInputItem from "./component/CodeInputItem";
import CodeOutputItem from "./component/CodeOutputItem";
import CodePythonItem from "./component/CodePythonItem";
import ConditionItem from "./component/ConditionItem";
import FileTypeSelect from "./component/FileTypeSelect";
import HistoryNumItem from "./component/HistoryNumItem";
import ImagePromptItem from "./component/ImagePromptItem";
import InputFormItemNew from "./component/InputFormItem";
import InputFormItemOld from "./component/InputFormItemOld";
import InputItem from "./component/InputItem";
import InputListItem from "./component/InputListItem";
import KnowledgeQaSelectItem from "./component/KnowledgeQaSelectItem";
import KnowledgeSelectItem from "./component/KnowledgeSelectItem";
import MetadataFilter from "./component/MetadataFilter";
import ModelItem from "./component/ModelItem";
import OutputItem from "./component/OutputItem";
import ReportItem from "./component/ReportItem";
import RetrievalWeightSlider from "./component/RetrievalWeightSlider";
import SliderItem, { SwitchSliderItem } from "./component/SliderItem";
import SqlConfigItem from "./component/SqlConfigItem";
import SwitchItem from "./component/SwitchItem";
import TextAreaItem from "./component/TextAreaItem";
import ToolItem from "./component/ToolItem";
import VarItem from "./component/VarItem";
import VarSelectItem, { VarSelectSingleItem } from "./component/VarSelectItem";
import VarTextareaItem from "./component/VarTextareaItem";
import VarTextareaUploadItem from "./component/VarTextareaUploadItem";
import GlobalVarItem from "./component/GlobalVarItem";

export default function Parameter({
    node,
    nodeId,
    item,
    onOutPutChange,
    onStatusChange,
    onVarEvent,
    onAddSysPrompt,
    selectedKnowledgeIds
}: {
    nodeId: string;
    node: WorkflowNode;
    item: WorkflowNodeParam;
    onOutPutChange: (key: string, value: any) => void;
    onStatusChange: (key: string, obj: any) => void;
    onVarEvent: (key: string, obj: any) => void;
    onAddSysPrompt: (type: 'knowledge' | 'sql') => void;
    onFouceUpdate: () => void;
}) {

    const handleOnNewValue = (newValue: any, validate?: any) => {
        item.value = newValue;
        if (validate) bindValidate(validate);
    };

    const bindValidate = (validate: any) => {
        onStatusChange(item.key, { param: item, validate });
    };

    const bindVarValidate = (validate: any) => {
        onVarEvent(item.key, { param: item, validate });
    };

    const addSysPrompt = (type: 'knowledge' | 'sql') => {
        if (node.type === 'agent') {
            onAddSysPrompt(type);
        }
    }

    const i18nPrefix = `node.${node.type}.${item.key}.`

    if (item.hidden) return null;

    const InputFormItem = node.v == 3 ? InputFormItemNew : InputFormItemOld;

    switch (item.type) {
        case 'textarea':
            return <TextAreaItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix} />;
        case 'input':
            return <InputItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix} />;
        case 'input_list':
            return <InputListItem node={node} data={item} preset={item.key === "preset_question"} onChange={handleOnNewValue} i18nPrefix={i18nPrefix} />;
        case 'var':
            return <VarItem node={node} data={item} i18nPrefix={i18nPrefix} />
        case 'chat_history_num':
            return <HistoryNumItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix} />
        case 'global_var': return <GlobalVarItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix} />;
        case 'form':
            return <InputFormItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />
        case 'var_textarea':
            return <VarTextareaItem
                node={node}
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />
        case 'var_textarea_file':
            return <VarTextareaUploadItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />
        case 'output_form':
            return <OutputItem
                nodeId={nodeId}
                node={node}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />
        case 'bisheng_model':
            return <ModelItem data={item} onChange={handleOnNewValue} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />
        case 'agent_model':
            return <ModelItem agent data={item} onChange={handleOnNewValue} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />
        case 'slide':
            return <SliderItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />
        case 'slide_switch':
            return <SwitchSliderItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />
        case 'switch':
            return <SwitchItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />;
        case 'var_select':
            return <VarSelectSingleItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate} i18nPrefix={i18nPrefix}
            />;
        case 'user_question':
            return <VarSelectItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onOutPutChange={onOutPutChange}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate} i18nPrefix={i18nPrefix}
            />;
        case 'knowledge_select_multi':
            return <KnowledgeSelectItem
                nodeId={nodeId}
                data={item}
                onChange={(val) => {
                    handleOnNewValue(val)
                    addSysPrompt('knowledge')
                }}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />;
        case 'qa_select_multi':
            return <KnowledgeQaSelectItem
                nodeId={nodeId}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />;
        case 'number':
            return <InputItem type='number' data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />;
        case 'char_number':
            return <InputItem char type='number' data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />;
        case 'code_input':
            return <CodeInputItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />;
        case 'code':
            return <CodePythonItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />;
        case 'code_output':
            return <CodeOutputItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />;
        case 'add_tool':
            return <ToolItem data={item} onChange={handleOnNewValue} i18nPrefix={i18nPrefix}
            />;
        case 'condition':
            return <ConditionItem
                nodeId={nodeId}
                node={node}
                data={item}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />;
        case 'report':
            return <ReportItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />;
        case 'sql_config':
            return <SqlConfigItem nodeId={nodeId} data={item} onChange={(val) => {
                handleOnNewValue(val)
                val.open && addSysPrompt('sql')
            }} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />;
        case 'select_fileaccept':
            return <FileTypeSelect
                data={item}
                onChange={(val) => {
                    // group_params[0] 受input模板影响
                    const imageFileItem = node.group_params[0].params.find(param => {
                        if (param.key === 'dialog_image_files') return true
                    })
                    imageFileItem.hidden = val === 'file'
                    handleOnNewValue(val)
                    // onFouceUpdate()
                }}
                i18nPrefix={i18nPrefix}
            />;
        case 'image_prompt':
            return <ImagePromptItem nodeId={nodeId} data={item} onChange={handleOnNewValue} onVarEvent={bindVarValidate} i18nPrefix={i18nPrefix}
            />;
        case 'search_switch':
            return <RetrievalWeightSlider data={item} onChange={handleOnNewValue} onValidate={bindValidate} i18nPrefix={i18nPrefix}
            />;
        case "metadata_filter": return (
            <MetadataFilter
                data={item}
                node={node}
                onChange={handleOnNewValue}
                onValidate={bindValidate}
                selectedKnowledgeIds={selectedKnowledgeIds}
                nodeId={nodeId}
                onVarEvent={bindVarValidate}
                i18nPrefix={i18nPrefix}
            />
        );
        default:
            return <div>Unsupported parameter type,{item.type}</div>;
    }
};
