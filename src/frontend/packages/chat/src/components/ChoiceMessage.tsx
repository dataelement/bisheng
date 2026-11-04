import { Button, Textarea } from '@bisheng/ui';
import { useRef, useState, type ReactNode } from 'react';

export interface ChoiceOption { id: string; label: ReactNode }
export interface ChoiceMessageProps {
  kind: 'input' | 'choice';
  canExecute: boolean;
  labels: { confirm: string; confirmed: string };
  selectedValue?: string;
  initialValue?: string;
  options?: readonly ChoiceOption[];
  onSubmit: (value: string) => void | Promise<void>;
  onError?: (error: unknown) => void;
  selectedIcon?: ReactNode;
}

/** Controlled host capability, local draft; no transport or application store. */
export function ChoiceMessage({ kind, canExecute, labels, selectedValue, initialValue = '', options = [], onSubmit, onError, selectedIcon }: ChoiceMessageProps) {
  const [draft, setDraft] = useState(initialValue);
  const [submitted, setSubmitted] = useState<string>();
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const selected = selectedValue ?? submitted;
  const confirmed = selected !== undefined && selected !== '';
  const disabled = !canExecute || confirmed || pending;
  const handleSubmit = async (value: string) => {
    if (!canExecute || confirmed || inFlight.current || !value.trim()) return;
    inFlight.current = true;
    setPending(true);
    try {
      await onSubmit(value);
      setSubmitted(value);
    } catch (error) {
      onError?.(error);
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };
  return <div className="mt-2">
    {kind === 'input' ? <>
      <Textarea value={confirmed ? selected : draft} onChange={event => setDraft(event.target.value)} disabled={disabled} />
      <div className="flex justify-end mt-2">
        <Button disabled={disabled} loading={pending} onClick={() => void handleSubmit(draft)}>{confirmed ? labels.confirmed : labels.confirm}</Button>
      </div>
    </> : options.map(option => <div key={option.id}
      role="button" tabIndex={disabled ? -1 : 0} aria-disabled={disabled}
      aria-pressed={selected === option.id}
      className="min-w-56 border dark:bg-background rounded-xl p-3 mt-2 hover:bg-gray-50 cursor-pointer flex justify-between items-center break-all"
      onClick={() => void handleSubmit(option.id)}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); void handleSubmit(option.id); }
      }}>
      {option.label}{selected === option.id && selectedIcon}
    </div>)}
  </div>;
}
