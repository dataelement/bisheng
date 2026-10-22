import { MessageFrame, WorkflowFileField, WorkflowForm } from '@bisheng/chat';
import { normalizeFormFields, type RawMessage } from '@bisheng/chat/core';
import type { ReactNode } from 'react';
import { useRecoilValue } from 'recoil';
import MultiSelect from '~/components/ui/MultiSelect';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/Select';
import { useToastContext } from '~/Providers';
import { useLocalize } from '~/hooks';
import { emitAreaTextEvent, EVENT_TYPE } from '../useAreaText';
import { normalizeFileAccept } from '../fileAcceptUtils';
import { bishengConfState } from '../store/atoms';
import InputFileComponent from './InputFileComponent';

interface InputFormProps { data: RawMessage; flow: { name: string }; logo?: ReactNode }
export function InputForm({ data, flow, logo }: InputFormProps) {
    const localize = useLocalize();
    const config = useRecoilValue(bishengConfState);
    const { showToast } = useToastContext();
    return <MessageFrame title={flow.name} logo={logo}>
        <WorkflowForm key={String(data.node_id)} fields={normalizeFormFields(data.value)} canExecute
            submitLabel={localize('com_ui_start')}
            requiredMessage={field => localize('com_ui_required_field', { field })}
            onInvalid={errors => showToast({ message: errors.join('\n'), status: 'warning' })}
            onSubmit={(values, message) => emitAreaTextEvent({ action: EVENT_TYPE.FORM_SUBMIT, data: values, nodeId: data.node_id, message })}
            renderField={({ id, field, value, disabled, onChange, onFileNameChange }) => {
                if (field.type === 'file') return <InputFileComponent isSSO disabled={disabled}
                    renderControl={props => <WorkflowFileField {...props} id={id} />}
                    placeholder={localize('com_file_current_empty')} value="" multiple={field.multiple}
                    onChange={onFileNameChange}
                    suffixes={normalizeFileAccept(field.raw.file_type, { mediaEnabled: !!config?.enable_media_upload })}
                    onFileChange={value => onChange(Array.isArray(value) ? value : value ? [value] : [])} />;
                if (field.type !== 'select') return null;
                if (field.multiple) return <MultiSelect multiple disabled={disabled} className=""
                    value={typeof value === 'string' ? value.split(',').filter(Boolean) : []}
                    options={field.options.map(text => ({ label: text, value: text }))}
                    placeholder={localize('com_ui_please_select')} onChange={values => onChange(values.join(','))} />;
                return <Select disabled={disabled} value={typeof value === 'string' ? value : undefined} onValueChange={onChange}>
                    <SelectTrigger><SelectValue placeholder="" /></SelectTrigger>
                    <SelectContent className="bg-white"><SelectGroup>{field.options.map(text => <SelectItem key={text} value={text}>{text}</SelectItem>)}</SelectGroup></SelectContent>
                </Select>;
            }} />
    </MessageFrame>;
}
export default InputForm;
