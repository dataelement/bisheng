import { Button, Textarea } from '@bisheng/ui';
import { useId, useRef, useState, type ReactNode } from 'react';
import { displayText } from '../core/normalizeHistory';
import { summarizeFormValues, validateFormValues, type WorkflowFormField } from '../core/workflowForm';
import '../styles/workflow-form.css';

export interface WorkflowFormFieldBinding {
  id: string;
  field: WorkflowFormField;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
  onFileNameChange: (name: string) => void;
}
export interface WorkflowFormProps {
  fields: readonly WorkflowFormField[];
  canExecute: boolean;
  submitLabel: string;
  requiredMessage: (label: string) => string;
  renderField?: (binding: WorkflowFormFieldBinding) => ReactNode;
  onSubmit: (values: Record<string, unknown>, summary: string) => void | Promise<void>;
  onInvalid?: (errors: string[]) => void;
  onError?: (error: unknown) => void;
}
/** Client form validation and submission; hosts only bind upload/select services. */
export function WorkflowForm({ fields, canExecute, submitLabel, requiredMessage, renderField, onSubmit, onInvalid, onError }: WorkflowFormProps) {
  const formId = useId();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const names = useRef<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const locked = useRef(false);
  const disabled = !canExecute || pending || submitted;
  const handleSubmit = async () => {
    if (!canExecute || locked.current || submitted) return;
    const errors = validateFormValues(fields, values, requiredMessage);
    if (errors.length) { onInvalid?.(errors); return; }
    locked.current = true; setPending(true);
    try {
      await onSubmit({ ...values }, summarizeFormValues(fields, values, names.current));
      setSubmitted(true);
    } catch (error) { onError?.(error); }
    finally { locked.current = false; setPending(false); }
  };
  return <div className="bisheng-chat-form max-h-[520px] overflow-y-auto space-y-2">
    {fields.map(field => <div key={field.key} className="w-full">
      <label htmlFor={`${formId}-${field.key}`}>{field.label}{field.required && <span className="text-red-500">*</span>}</label>
      <div className="mb-2">
        {field.type === 'text' ? <Textarea id={`${formId}-${field.key}`} maxLength={10000} disabled={disabled}
          value={displayText(values[field.key])} onChange={event => setValues(previous => ({ ...previous, [field.key]: event.target.value }))} />
          : renderField?.({ id: `${formId}-${field.key}`, field, value: values[field.key], disabled,
            onChange: value => { if (!disabled) setValues(previous => ({ ...previous, [field.key]: value })); },
            onFileNameChange: name => { if (!disabled) names.current[field.key] = name; } })}
      </div>
    </div>)}
    <div className="flex justify-end"><Button onClick={() => void handleSubmit()} disabled={disabled} loading={pending}>{submitLabel}</Button></div>
  </div>;
}
