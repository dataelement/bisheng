import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { MoveConfirmation } from './MoveConfirmation';

interface MoveConfirmationOptions {
  title?: string;
  description?: ReactNode;
  cancelText?: string;
  confirmText?: string;
}

export function useMoveConfirmation() {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.move' });
  const [options, setOptions] = useState<MoveConfirmationOptions | null>(null);
  const pending = useRef<((confirmed: boolean) => void) | null>(null);
  const confirm = useCallback((next: MoveConfirmationOptions) => {
    pending.current?.(false);
    setOptions(next);
    return new Promise<boolean>((resolve) => { pending.current = resolve; });
  }, []);
  const settle = useCallback((confirmed: boolean) => {
    const resolve = pending.current;
    pending.current = null;
    setOptions(null);
    resolve?.(confirmed);
  }, []);
  useEffect(() => () => {
    pending.current?.(false);
    pending.current = null;
  }, []);

  return {
    confirm,
    confirmationDialog: options ? <MoveConfirmation open title={options.title ?? t('title')}
      description={options.description} cancelText={options.cancelText ?? t('cancel')}
      confirmText={options.confirmText ?? t('move_here')} onCancel={() => settle(false)} onConfirm={() => settle(true)} /> : null,
  };
}
