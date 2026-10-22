import { MessageFrame, WorkflowFileField, WorkflowForm } from '@bisheng/chat';
import { normalizeFormFields, type RawMessage } from '@bisheng/chat/core';
import { toast } from '@bisheng/ui';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select';
import MultiSelect from '@/components/bs-ui/select/multi';
import InputFileComponent from '@/components/inputFileComponent';
import { locationContext } from '@/contexts/locationContext';
import { fileAcceptToInputAccept, normalizeFileAccept } from '@/util/fileAcceptUtils';
import { useContext, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function InputForm({ data, title, logo, onSubmit }: { data: RawMessage; title: string; logo?: ReactNode; onSubmit: (values: Record<string, unknown>, summary: string) => void }) {
    const { t } = useTranslation();
    const { appConfig } = useContext(locationContext);
    return <MessageFrame title={title} logo={logo}>
        <WorkflowForm key={String(data.node_id)} fields={normalizeFormFields(data.value)} canExecute
            submitLabel={t('report.start')} requiredMessage={label => t('report.requiredField', { label })}
            onInvalid={errors => toast.show({ type: 'warning', message: errors.join('\n') })}
            onSubmit={onSubmit}
            renderField={({ id, field, value, disabled, onChange, onFileNameChange }) => {
                if (field.type === 'file') return <InputFileComponent isSSO disabled={disabled}
                    renderControl={props => <WorkflowFileField {...props} id={id} />}
                    placeholder={t('report.fileRequired')} value="" multiple={field.multiple}
                    onChange={name => onFileNameChange(Array.isArray(name) ? name.join('\n') : name)}
                    suffixes={fileAcceptToInputAccept(normalizeFileAccept(field.raw.file_type, { mediaEnabled: !!appConfig.enableMediaUpload }))}
                    onFileChange={value => onChange(Array.isArray(value) ? value : value ? [value] : [])} />;
                if (field.type !== 'select') return null;
                if (field.multiple) return <MultiSelect multiple disabled={disabled} className=""
                    value={typeof value === 'string' ? value.split(',').filter(Boolean) : []}
                    options={field.options.map(text => ({ label: text, value: text }))}
                    placeholder={t('flow:selectOption')} onChange={values => onChange(values.join(','))} />;
                return <Select disabled={disabled} value={typeof value === 'string' ? value : undefined} onValueChange={onChange}>
                    <SelectTrigger><SelectValue placeholder="" /></SelectTrigger>
                    <SelectContent><SelectGroup>{field.options.map(text => <SelectItem key={text} value={text}>{text}</SelectItem>)}</SelectGroup></SelectContent>
                </Select>;
            }} />
    </MessageFrame>;
}
export default InputForm;
