import { MessageFrame, WorkflowFileField, WorkflowForm } from '@bisheng/chat';
import { normalizeFormFields, type RawMessage } from '@bisheng/chat/core';
import { Select, toast } from '@bisheng/ui';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import InputFileComponent from '@/components/inputFileComponent';
import { locationContext } from '@/contexts/locationContext';
import { fileAcceptToInputAccept, normalizeFileAccept } from '@/util/fileAcceptUtils';
import { useContext, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function InputForm({ data, title, logo, onSubmit }: { data: RawMessage; title: string; logo?: ReactNode; onSubmit: (values: Record<string, unknown>, summary: string) => void }) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();
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
                const options = field.options.map(text => ({ label: text, value: text }));
                if (field.multiple) return <Select {...selectLabels} multiple disabled={disabled}
                    value={typeof value === 'string' ? value.split(',').filter(Boolean) : []}
                    options={options} placeholder={t('flow:selectOption')} aria-label={field.label}
                    onChange={values => onChange(values.join(','))} />;
                return <Select {...selectLabels} disabled={disabled} value={typeof value === 'string' ? value : null}
                    options={options} placeholder={t('flow:selectOption')} aria-label={field.label}
                    onChange={value => onChange(value ?? '')} />;
            }} />
    </MessageFrame>;
}
export default InputForm;
