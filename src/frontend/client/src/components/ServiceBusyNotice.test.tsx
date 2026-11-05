/** @jest-environment node */

import { renderToStaticMarkup } from 'react-dom/server';
import { ChatErrorCard } from './ChatErrorCard';
import { ServiceBusyNotice } from './ServiceBusyNotice';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => ({
    'com_error_retry': 'Retry',
    'com_message.rate_limit_title': 'Model service busy',
    'com_message.rate_limit_recovering_desc': 'The system is checking whether the model has recovered.',
    'com_message.rate_limit_busy_desc': 'You can retry or switch models.',
    'com_message.rate_limit_recovered_title': 'Model service restored',
    'com_message.rate_limit_recovered_desc': 'The current model has recovered.',
    'com_message.switch_model': 'Switch model',
    'com_message.try_later': 'Try later',
    'com_linsight_error_title_rate_limit': 'Legacy title',
    'com_linsight_error_desc_rate_limit': 'Legacy description',
    'com_linsight_error_hint_rate_limit': '',
    'com_linsight_error_title_network_timeout': 'Timeout',
    'com_linsight_error_desc_network_timeout': 'Try again.',
    'com_linsight_error_hint_network_timeout': '',
  })[key] ?? key,
}));

jest.mock('~/components/ui/Button', () => ({
  // Mirrors the real Button's contract for what these tests assert on: the
  // design-system props are consumed (not spread onto the DOM node) and
  // `loading` surfaces as aria-busy + blocked interaction, same as @bisheng/ui.
  Button: ({
    children,
    icon,
    loading,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    icon?: React.ReactNode;
    loading?: boolean;
  }) => (
    <button aria-busy={loading || undefined} disabled={loading || props.disabled} {...props}>
      {icon}
      {children}
    </button>
  ),
}));

describe('ServiceBusyNotice', () => {
  it.each([
    ['recovering', 'The system is checking whether the model has recovered.'],
    ['busy', 'You can retry or switch models.'],
    ['normal', 'The current model has recovered.'],
  ] as const)('renders the %s execution state with neutral copy', (state, copy) => {
    const markup = renderToStaticMarkup(
      <ServiceBusyNotice rateLimitState={state} onRetry={() => undefined} />,
    );
    expect(markup).toContain('role="status"');
    expect(markup).toContain(copy);
    expect(markup).not.toContain('text-red');
  });

  it('blocks retry while the recovery command is pending', () => {
    const markup = renderToStaticMarkup(
      <ServiceBusyNotice rateLimitState="busy" onRetry={() => undefined} retrying />,
    );
    expect(markup).toContain('aria-busy="true"');
  });

  it('never exposes raw provider detail for a rate-limit error', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard
        errorType="rate_limit"
        detail="secret provider request id"
        fallbackMessage="secret fallback"
      />,
    );
    expect(markup).not.toContain('secret provider request id');
    expect(markup).not.toContain('secret fallback');
    expect(markup).not.toContain('view_detail');
  });

  it('keeps legacy non-rate-limit diagnostics private', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard errorType="network_timeout" detail="diagnostic detail" />,
    );
    expect(markup).not.toContain('com_linsight_error_view_detail');
    expect(markup).not.toContain('diagnostic detail');
  });

  it('uses safe recovery copy when an old rejection includes raw text', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard
        errorType="recovery_rejected"
        fallbackMessage="This request can no longer be retried."
      />,
    );
    expect(markup).toContain('You can retry or switch models.');
    expect(markup).not.toContain('This request can no longer be retried.');
    expect(markup).not.toContain('com_linsight_error_title_unknown');
    expect(markup).not.toContain('com_linsight_error_desc_unknown');
  });
});

describe('service failure classification', () => {
  const failure = { version: 1, failure_id: 'failure-one', category: 'database', service_name: 'Search index', occurred_at: '2026-11-05T08:00:00+08:00' };

  it('shows fixed service copy without exposing legacy detail or changing retry eligibility', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard errorType="network_timeout" failureInfo={failure} detail="private diagnostic" onRetry={() => undefined} />,
    );
    expect(markup).toContain('api_errors.failure_database');
    expect(markup).toContain('Search index');
    expect(markup).toContain('2026-11-05T08:00:00+08:00');
    expect(markup).toContain('Retry');
    expect(markup).not.toContain('private diagnostic');
  });

  it('keeps recovery-in-progress copy while the existing model retry runs', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard errorType="rate_limit" failureInfo={failure} rateLimitState="recovering" />,
    );
    expect(markup).toContain('The system is checking whether the model has recovered.');
    expect(markup).not.toContain('api_errors.failure_database');
  });

  it('falls back to the existing generic card for an unknown metadata version', () => {
    const markup = renderToStaticMarkup(<ChatErrorCard failureInfo={{ ...failure, version: 2 }} />);
    expect(markup).toContain('com_linsight_error_title_unknown');
    expect(markup).not.toContain('Search index');
  });
});


describe('public failure details', () => {
  it.each(['search', 'invoke_model', 'read_file', 'write_file', 'parse_file', 'transcribe', 'synthesize', 'authenticate', 'enqueue', 'upload', 'download', 'rerank', 'embed', 'tool_call'])('localizes the safe %s operation token', (operation) => {
    const markup = renderToStaticMarkup(<ChatErrorCard failureInfo={{ version: 1, failure_id: 'safe-reference', category: 'model_service', service: 'embedding', operation, occurred_at: '2026-11-05T08:00:00Z' }} />);
    expect(markup).toContain(`api_errors.failure_operation_${operation}`);
    expect(markup).toContain('api_errors.failure_service_embedding');
    expect(markup).toContain('safe-reference');
  });
  it('does not display unknown operation tokens or extension payloads', () => {
    const markup = renderToStaticMarkup(<ChatErrorCard failureInfo={{ version: 1, failure_id: 'safe-reference', category: 'network', service: 'internal_component', operation: 'private_operation', private_detail: 'password=hidden', occurred_at: '2026-11-05T08:00:00Z' }} />);
    expect(markup).toContain('api_errors.failure_service_network');
    expect(markup).not.toContain('internal_component');
    expect(markup).not.toContain('private_operation');
    expect(markup).not.toContain('password=hidden');
  });
});
