import { MessageFrame, WorkflowFileField, WorkflowForm } from '@bisheng/chat';
import { normalizeFormFields, type RawMessage } from '@bisheng/chat/core';
import type { ReactNode } from 'react';
import { useRecoilValue } from 'recoil';
import { Select } from '@bisheng/ui';
import useSelectCopy from '~/hooks/useSelectCopy';
import { useToastContext } from '~/Providers';
import { useLocalize } from '~/hooks';
import { emitAreaTextEvent, EVENT_TYPE } from '../useAreaText';
import { normalizeFileAccept } from '../fileAcceptUtils';
import { bishengConfState } from '../store/atoms';
import InputFileComponent from './InputFileComponent';

interface InputFormProps { data: RawMessage; flow: { name: string }; logo?: ReactNode }
export function InputForm({ data, flow, logo }: InputFormProps) {
    const localize = useLocalize();
    const selectCopy = useSelectCopy();
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
                const options = field.options.map(text => ({ label: text, value: text }));
                if (field.multiple) return <Select {...selectCopy} multiple disabled={disabled}
                    value={typeof value === 'string' ? value.split(',').filter(Boolean) : []}
                    options={options} placeholder={localize('com_ui_please_select')} aria-label={field.label}
                    onChange={values => onChange(values.join(','))} />;
                return <Select {...selectCopy} disabled={disabled} value={typeof value === 'string' ? value : null}
                    options={options} placeholder={localize('com_ui_please_select')} aria-label={field.label}
                    onChange={value => onChange(value ?? '')} />;
            }} />
    </MessageFrame>;
}
export default InputForm;
