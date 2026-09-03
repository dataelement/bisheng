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
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { Button } from '~/components/ui/Button';
import { cn } from '~/utils';

/**
 * Animated dashboard-gauge icon (designer-supplied SVG, SMIL animation baked
 * in): the needle sweeps back and forth — the visual for "service under
 * load". Strokes use currentColor so the host's text color drives it.
 */
function BusyGaugeIcon({ size = 16, className }: { size?: number; className?: string }) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
            className={className}
        >
            <path
                d="M14.9985 10.9781C14.9985 10.9781 13.4608 15.3126 12.73 16.0693C11.9993 16.826 10.7934 16.8471 10.0367 16.1163C9.27995 15.3855 9.25891 14.1797 9.98967 13.423C10.7204 12.6662 14.9985 10.9781 14.9985 10.9781Z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinejoin="round"
            >
                <animateTransform
                    attributeName="transform"
                    type="rotate"
                    values="-180 11.36 14.77; 92 11.36 14.77; -180 11.36 14.77"
                    keyTimes="0; 0.5; 1"
                    calcMode="spline"
                    keySplines="0.45 0 0.55 1; 0.45 0 0.55 1"
                    dur="2.4s"
                    repeatCount="indefinite"
                />
            </path>
            <path
                d="M19.071 20.5355C20.8807 18.7259 22 16.2259 22 13.4645C22 7.94162 17.5229 3.46448 12 3.46448C6.47714 3.46448 2 7.94162 2 13.4645C2 16.2259 3.11929 18.7259 4.92893 20.5355"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path d="M12 3.94067V5.84544" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M19.0692 7.34167L17.5889 8.54034" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M20.8203 15.0039L18.9644 14.5754" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M3.17969 15.0039L5.03563 14.5754" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M4.93091 7.34167L6.41118 8.54039" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
}

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
    /** Header icon: the animated 'gauge' (service under load, default) or the
        static gray 'attention' mark (e.g. network timeout — not a load issue). */
    icon?: 'gauge' | 'attention';
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
    icon = 'gauge',
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

    // Right-aligned action group. It rides the description's last line when
    // there is no detail disclosure, and the 查看详情 row when there is one —
    // rendered from this one element so the two placements can't drift. A
    // rate-limited execution offers two more ways out than a plain failure:
    // move the same request to another model, or leave it be.
    const actions = onRetry || onSwitchModel || onLater ? (
        <div className="flex shrink-0 items-center gap-2">
            {onRetry && (
                <Button
                    color="default"
                    variant="filled"
                    size="small"
                    icon={<Outlined.Refresh />}
                    loading={retrying}
                    onClick={onRetry}
                >
                    {localize('com_error_retry')}
                </Button>
            )}
            {onSwitchModel && (
                <Button
                    color="primary"
                    variant="filled"
                    size="small"
                    disabled={retrying}
                    onClick={onSwitchModel}
                >
                    {localize('com_message.switch_model')}
                </Button>
            )}
            {onLater && (
                <Button
                    color="default"
                    variant="text"
                    size="small"
                    disabled={retrying}
                    onClick={onLater}
                >
                    {localize('com_message.try_later')}
                </Button>
            )}
        </div>
    ) : null;

    return (
        <div
            role="status"
            className={cn('my-2 rounded-2xl border border-border bg-bg-page p-4 text-sm', className)}
        >
            <div className="flex items-start gap-2.5">
                {icon === 'attention' ? (
                    <Outlined.Attention size={16} className="mt-0.5 shrink-0 text-text-3" />
                ) : (
                    <BusyGaugeIcon size={16} className="mt-0.5 shrink-0 text-text-3" />
                )}
                <div className="min-w-0 flex-1">
                    {displayTitle && <div className="font-medium text-text-2">{displayTitle}</div>}
                    {/* No detail disclosure → the actions share the description's
                        row, bottom-aligned so they read as centered on its LAST
                        line (24px button ≈ the ~23px line box). */}
                    <div className={cn('flex items-end gap-3', displayTitle && 'mt-1')}>
                        <p className="min-w-0 flex-1 leading-relaxed text-text-3">{displayDescription}</p>
                        {!detail && actions}
                    </div>

                    {/* With a detail disclosure the actions move down here instead,
                        vertically centered on the 查看详情 row (toggle left, buttons
                        right). */}
                    {detail && (
                        <div className="mt-2.5 flex items-center justify-between gap-3">
                            <button
                                type="button"
                                onClick={() => setShowDetail((v) => !v)}
                                className="inline-flex items-center gap-1 text-body text-gray-400 transition-colors hover:text-gray-600"
                            >
                                {localize(showDetail ? 'com_linsight_error_hide_detail' : 'com_linsight_error_view_detail')}
                                {showDetail ? <Outlined.Down size={14} /> : <Outlined.Right size={14} />}
                            </button>
                            {actions}
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
