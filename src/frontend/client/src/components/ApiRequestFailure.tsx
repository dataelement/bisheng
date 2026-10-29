import { Alert } from '@bisheng/ui';
import { isApiError } from '@bisheng/api-client';
import { useLocalize } from '~/hooks';
import { showApiError } from '~/api/request';

interface ApiRequestFailureProps {
  error: unknown;
  onRetry?: () => unknown;
}

export function ApiRequestFailure({ error, onRetry }: ApiRequestFailureProps) {
  const localize = useLocalize();
  if (!error || (isApiError(error) && error.kind === 'canceled')) return null;
  return <Alert type="error" live
    description={error instanceof Error ? error.message : localize('com_ui_error')}
    actions={onRetry ? [{ label: localize('com_ui_retry'), onClick: () => {
      void Promise.resolve().then(onRetry).catch(showApiError);
    } }] : undefined}
  />;
}
