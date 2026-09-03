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

  it('preserves existing detail behavior for a non-rate-limit transient error', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard errorType="network_timeout" detail="diagnostic detail" />,
    );
    expect(markup).toContain('com_linsight_error_view_detail');
  });

  it('uses the localized API error as the primary recovery-rejected message', () => {
    const markup = renderToStaticMarkup(
      <ChatErrorCard
        errorType="recovery_rejected"
        fallbackMessage="This request can no longer be retried."
      />,
    );
    expect(markup).toContain('This request can no longer be retried.');
    expect(markup).not.toContain('com_linsight_error_title_unknown');
    expect(markup).not.toContain('com_linsight_error_desc_unknown');
  });
});
