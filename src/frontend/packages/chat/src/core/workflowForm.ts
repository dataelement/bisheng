import { asRecord, displayText, sourceId } from './normalizeHistory';
import type { RawMessage } from './types';
export interface WorkflowFormField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  multiple: boolean;
  options: string[];
  raw: RawMessage;
}
export function normalizeFormFields(value: unknown): WorkflowFormField[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => {
    const raw = asRecord(item); const key = sourceId(raw.key);
    if (key === undefined) return [];
    return [{ key, label: displayText(raw.value ?? raw.label), type: String(raw.type ?? 'text'), required: raw.required === true,
      multiple: raw.multiple === true,
      options: Array.isArray(raw.options) ? raw.options.flatMap(option => {
        const text = sourceId(asRecord(option).text); return text === undefined ? [] : [text];
      }) : [], raw }];
  });
}
function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'string' && value.trim() === '')
    || (Array.isArray(value) && (value.length === 0 || value.every(isEmpty)));
}
export function validateFormValues(fields: readonly WorkflowFormField[], values: Readonly<Record<string, unknown>>, requiredMessage: (label: string) => string): string[] {
  return fields.flatMap(field => field.required && isEmpty(values[field.key]) ? [requiredMessage(field.label)] : []);
}
export function summarizeFormValues(fields: readonly WorkflowFormField[], values: Readonly<Record<string, unknown>>, fileNames: Readonly<Record<string, string>>): string {
  return fields.map(field => `${field.label}:${field.type === 'file' ? fileNames[field.key] ?? '' : displayText(values[field.key] ?? '')}\n`).join('');
}
