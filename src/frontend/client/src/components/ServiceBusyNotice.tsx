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
    desc: string;
    /** optional localized title, e.g. "模型服务繁忙" (task mode shows it; daily chat omits it) */
    title?: string;
    /** raw provider text kept behind a "view details" disclosure (task mode) */
    detail?: string;
    /** when provided, a low-key Retry button re-runs the request */
    onRetry?: () => void;
    /** disables the retry button + spins its icon while a retry is in flight */
    retrying?: boolean;
    className?: string;
}

export function ServiceBusyNotice({ desc, title, detail, onRetry, retrying, className }: ServiceBusyNoticeProps) {
    const localize = useLocalize();
    const [showDetail, setShowDetail] = useState(false);

    return (
        <div
            role="status"
            className={cn('my-2 rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm', className)}
        >
            <div className="flex items-start gap-2.5">
                <Clock size={18} className="mt-0.5 shrink-0 text-gray-400" />
                <div className="min-w-0 flex-1">
                    {title && <div className="font-medium text-gray-700">{title}</div>}
                    <p className={cn('leading-relaxed text-gray-500', title && 'mt-1')}>{desc}</p>

                    {(onRetry || detail) && (
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
