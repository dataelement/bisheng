import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { CrawlFeedbackDialog } from './CrawlFeedbackDialog';
import { CrawlQueuePanel } from './CrawlQueuePanel';
import { crawlErrorMessageKey, mapCrawlError, normalizeCrawlUrl } from './crawlErrorUtils';
import { useCrawlQueue } from '../hooks/useCrawlQueue';
import { addWebsiteSourceApi, crawlTempSourceApi, getFeedbackTips } from '~/api/channels';
import zh from '~/locales/zh-Hans/translation.json';

jest.mock('~/api/request', () => ({ translateApiErrorMessage: jest.fn() }));
jest.mock('~/api/channels', () => ({ addWebsiteSourceApi: jest.fn(), crawlTempSourceApi: jest.fn(), getFeedbackTips: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key.split('.').reduce<unknown>((obj, part) => (obj as Record<string, unknown>)?.[part], jest.requireActual('~/locales/zh-Hans/translation.json')) ?? key }));
jest.mock('~/utils', () => ({ generateUUID: () => Math.random().toString(), cn: (...values: string[]) => values.filter(Boolean).join(' ') }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/common', () => ({ NotificationSeverity: { WARNING: 'warning' } }));
jest.mock('p-limit', () => () => (fn: () => Promise<void>) => fn());

const crawl = jest.mocked(crawlTempSourceApi);
const add = jest.mocked(addWebsiteSourceApi);
const feedback = jest.mocked(getFeedbackTips);

it.each(['https://', 'https://bad host/news', 'javascript:alert(1)', 'https://user:pass@example.com', 'https:/example.com', ''])('rejects malformed URL %s', input => {
    expect(normalizeCrawlUrl(input)).toBeNull();
});
it.each(['https://example.com/news', 'example.com/news', ' https://example.com/news '])('normalizes website URL %s', input => {
    expect(normalizeCrawlUrl(input)).toBe('https://example.com/news');
});
it.each([
    [{ status_code: 19004 }, 19004], [{ response: { data: { status_code: '13005' } } }, 19005],
    [{ code: 'ERR_NETWORK' }, 'network'], [{ code: 'ECONNABORTED' }, 'timeout'],
    [{ status_code: 19006 }, 19006], [{ status_code: 19007 }, 19007], [{}, 19003],
])('preserves known failure causes %j', (error, expected) => {
    expect(mapCrawlError(error)).toBe(expected);
});
it('shows an invalid URL reason immediately and skips both requests', () => {
    const { result } = renderHook(() => useCrawlQueue({ onSourceAdded: jest.fn() }));
    act(() => result.current.enqueue('https://'));
    expect(result.current.queue[0]).toMatchObject({ status: 'failed', errorCode: 'invalid_url' });
    expect(result.current.panelOpen).toBe(true);
    expect(crawl).not.toHaveBeenCalled();
    expect(add).not.toHaveBeenCalled();
});
it.each([19003, 19004, 19005, 19006])('keeps the queue open after crawl error %s', async code => {
    crawl.mockRejectedValueOnce({ status_code: code });
    const onSourceAdded = jest.fn();
    const { result } = renderHook(() => useCrawlQueue({ onSourceAdded }));
    act(() => result.current.enqueue('https://example.com/news'));
    await waitFor(() => expect(result.current.queue[0].status).toBe('failed'));
    expect(result.current.queue[0].errorCode).toBe(code);
    expect(result.current.panelOpen).toBe(true);
    expect(add).not.toHaveBeenCalled();
    expect(onSourceAdded).not.toHaveBeenCalled();
});
it('preserves a save failure and permits removing the failed entry', async () => {
    crawl.mockResolvedValueOnce({ data: { name: 'News', article_links: [] } });
    add.mockRejectedValueOnce({ status_code: 19007 });
    const { result } = renderHook(() => useCrawlQueue({ onSourceAdded: jest.fn() }));
    act(() => result.current.enqueue('example.com/news'));
    await waitFor(() => expect(result.current.queue[0].errorCode).toBe(19007));
    act(() => result.current.abort(result.current.queue[0].id));
    expect(result.current.queue).toHaveLength(0);
});
it('adds a valid source and collapses the successful queue', async () => {
    crawl.mockResolvedValueOnce({ data: { name: 'News', article_links: [] } });
    add.mockResolvedValueOnce({ data: { id: 'source-1', name: 'News' } });
    const onSourceAdded = jest.fn();
    const { result } = renderHook(() => useCrawlQueue({ onSourceAdded }));
    act(() => result.current.enqueue('example.com/news'));
    await waitFor(() => expect(result.current.queue[0].status).toBe('success'));
    expect(crawl).toHaveBeenCalledWith({ url: 'https://example.com/news' }, expect.any(Object));
    expect(onSourceAdded).toHaveBeenCalledWith(expect.objectContaining({ id: 'source-1' }));
    expect(result.current.panelOpen).toBe(false);
});
it('renders the failure reason without hover and opens manual help by click', () => {
    const onOpenFeedback = jest.fn();
    const onAbort = jest.fn();
    render(<CrawlQueuePanel queue={[{ id: '1', url: 'https://', status: 'failed', errorCode: 'invalid_url', abortController: new AbortController() }]}
        inProgressCount={0} panelOpen onPanelOpenChange={jest.fn()} onAbort={onAbort} onOpenPreview={jest.fn()} onOpenFeedback={onOpenFeedback} />);
    expect(screen.getByRole('status')).toHaveTextContent(zh.com_subscription.crawl_error_invalid_url);
    fireEvent.click(screen.getByText(zh.com_subscription.submit_manual_crawl_request));
    expect(onOpenFeedback).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByLabelText(zh.cancel));
    expect(onAbort).toHaveBeenCalledWith('1');
});
it.each([{ feedback_tips: '' }, { feedback_tips: 'Please email XXXX@XX' }, { data: null, inherited_from_root: true }, {}])('uses administrator guidance for empty or placeholder configuration %j', async config => {
    feedback.mockResolvedValueOnce(config);
    render(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByText(zh.com_subscription.send_crawl_requirement_to_email)).toBeVisible();
    expect(screen.queryByText(/XXXX@XX/)).toBeNull();
});
it('uses administrator guidance when config loading fails', async () => {
    feedback.mockRejectedValueOnce(new Error('offline'));
    render(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByText(zh.com_subscription.send_crawl_requirement_to_email)).toBeVisible();
});
it('shows configured guidance and refreshes it when reopened', async () => {
    feedback.mockResolvedValueOnce({ feedback_tips: 'Contact the service desk.' });
    const { rerender } = render(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByText('Contact the service desk.')).toBeVisible();
    rerender(<CrawlFeedbackDialog open={false} onOpenChange={jest.fn()} />);
    feedback.mockResolvedValueOnce({ feedback_tips: '' });
    rerender(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByText(zh.com_subscription.send_crawl_requirement_to_email)).toBeVisible();
    expect(screen.queryByText('Contact the service desk.')).toBeNull();
});
it('uses localized catalogues for account/service errors', () => {
    expect(crawlErrorMessageKey(19001)).toBe('api_errors.19001');
    expect(crawlErrorMessageKey(19006)).toBe('api_errors.19006');
});

it('reads the tenant configuration envelope returned by the feedback API', async () => {
    feedback.mockResolvedValueOnce({ data: { feedback_tips: 'Contact support@example.org' }, inherited_from_root: true });
    render(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByText('Contact support@example.org')).toBeVisible();
});
it('discards a configuration response after closing and reopening', async () => {
    let resolveOld!: (value: { feedback_tips: string }) => void;
    feedback.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    const { rerender } = render(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    rerender(<CrawlFeedbackDialog open={false} onOpenChange={jest.fn()} />);
    feedback.mockResolvedValueOnce({ feedback_tips: 'Current support contact' });
    rerender(<CrawlFeedbackDialog open onOpenChange={jest.fn()} />);
    expect(await screen.findByText('Current support contact')).toBeVisible();
    await act(async () => resolveOld({ feedback_tips: 'Old support contact' }));
    expect(screen.getByText('Current support contact')).toBeVisible();
    expect(screen.queryByText('Old support contact')).toBeNull();
});
