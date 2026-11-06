import { Outlined } from 'bisheng-icons';
import '../styles/workflow-form.css';

export interface WorkflowFileFieldProps {
  id?: string;
  value?: string;
  placeholder?: string;
  disabled?: boolean;
  loading?: boolean;
  onClick: () => void;
}
/** One client-based file field; upload requests remain in the host adapter. */
export function WorkflowFileField({ id, value, placeholder = '', disabled, loading, onClick }: WorkflowFileFieldProps) {
  return <button id={id} type="button" disabled={disabled || loading} onClick={onClick}
    className="bisheng-chat-file-field flex w-full min-w-0 items-center justify-between gap-2 rounded-md border px-2 text-left disabled:cursor-not-allowed disabled:opacity-50">
    <span className="min-w-0 flex-1 truncate">{value || placeholder}</span>
    <span className="flex size-8 shrink-0 items-center justify-center">{loading ? <Outlined.Loading className="size-[18px] animate-spin" /> : <Outlined.FileSearch size={18} />}</span>
  </button>;
}
