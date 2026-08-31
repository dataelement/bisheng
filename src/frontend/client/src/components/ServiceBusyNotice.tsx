/**
 * Neutral "service busy / try again" notice for TRANSIENT, retryable model errors
 * (rate limit / network timeout / service unavailable).
 *
 * Deliberately calm: an upstream throttle is the model vendor's availability
 * hiccup, not a BiSheng fault, so it uses the app's neutral banner styling (grey,
 * role="status") — never the red danger card reserved for genuine failures. Shared
 * by the Linsight task-mode failure card and the daily-mode chat error bubble so
 * both surfaces read identically.
 */
import { ChevronDown, ChevronRight, Clock, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { Button } from '~/components/ui/Button';
import { cn } from '~/utils';

interface ServiceBusyNoticeProps {
    /** localized one-line description, e.g. "当前使用人数较多，请稍后再试。" */
    desc?: string;
    /** optional localized title, e.g. "模型服务繁忙" (task mode shows it; daily chat omits it) */
    title?: string;
    /** raw provider text kept behind a "view details" disclosure (task mode) */
    detail?: string;
    /** when provided, a low-key Retry button re-runs the request */
    onRetry?: () => void;
    /** disables the retry button + spins its icon while a retry is in flight */
    retrying?: boolean;
    /** Model-level state projected by the backend for a rate-limited execution. */
    rateLimitState?: 'normal' | 'recovering' | 'busy';
    /** Opens the compatible-model chooser. */
    onSwitchModel?: () => void;
    /** Leaves the original request untouched and dismisses any parent UI. */
    onLater?: () => void;
    className?: string;
}

export function ServiceBusyNotice({
    desc,
    title,
    detail,
    onRetry,
    retrying,
    rateLimitState,
    onSwitchModel,
    onLater,
    className,
}: ServiceBusyNoticeProps) {
    const localize = useLocalize();
    const [showDetail, setShowDetail] = useState(false);
    const displayTitle = rateLimitState
        ? localize(
            rateLimitState === 'normal'
                ? 'com_message.rate_limit_recovered_title'
                : 'com_message.rate_limit_title',
        )
        : title;
    const displayDescription = rateLimitState
        ? localize(
            rateLimitState === 'normal'
                ? 'com_message.rate_limit_recovered_desc'
                : rateLimitState === 'recovering'
                ? 'com_message.rate_limit_recovering_desc'
                : 'com_message.rate_limit_busy_desc',
        )
        : desc;

    return (
        <div
            role="status"
            className={cn('my-2 rounded-2xl border border-border bg-fill-1 p-4 text-sm', className)}
        >
            <div className="flex items-start gap-2.5">
                <Clock size={18} className="mt-0.5 shrink-0 text-text-3" />
                <div className="min-w-0 flex-1">
                    {displayTitle && <div className="font-medium text-text-2">{displayTitle}</div>}
                    <p className={cn('leading-relaxed text-text-3', displayTitle && 'mt-1')}>
                        {displayDescription}
                    </p>

                    {(onRetry || onSwitchModel || onLater || detail) && (
                        <div className="mt-2.5 flex items-center gap-3">
                            {onRetry && (
                                <Button
                                    variant="secondaryBrand"
                                    size="sm"
                                    className="h-7 gap-1 px-2.5"
                                    disabled={retrying}
                                    onClick={onRetry}
                                >
                                    <RefreshCw size={13} className={retrying ? 'animate-spin' : undefined} />
                                    {localize('com_error_retry')}
                                </Button>
                            )}
                            {onSwitchModel && (
                                <Button
                                    variant="secondaryBrand"
                                    size="sm"
                                    className="h-7 px-2.5"
                                    disabled={retrying}
                                    onClick={onSwitchModel}
                                >
                                    {localize('com_message.switch_model')}
                                </Button>
                            )}
                            {onLater && (
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 px-2.5"
                                    disabled={retrying}
                                    onClick={onLater}
                                >
                                    {localize('com_message.try_later')}
                                </Button>
                            )}
                            {detail && (
                                <button
                                    type="button"
                                    onClick={() => setShowDetail((v) => !v)}
                                    className="inline-flex items-center gap-1 text-xs text-gray-400 transition-colors hover:text-gray-600"
                                >
                                    {showDetail ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                    {localize(showDetail ? 'com_linsight_error_hide_detail' : 'com_linsight_error_view_detail')}
                                </button>
                            )}
                        </div>
                    )}

                    {detail && showDetail && (
                        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-100 p-2.5 text-xs leading-relaxed text-gray-500">
                            {detail}
                        </pre>
                    )}
                </div>
            </div>
        </div>
    );
}
