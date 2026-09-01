/**
 * Friendly, classified failure card for a chat turn (灵思LLM容错与失败态友好交互).
 *
 * Replaces the old red box that dumped the raw provider error (e.g. an English
 * aliyun "inappropriate content" message + a doc URL) on end users. The backend
 * ships a stable `error_type` (content_filter / quota_exhausted / network_timeout
 * …) on the failure event; this card renders a localized title + explanation +
 * actionable hint per type, and keeps the raw provider text behind a "view
 * details" disclosure.
 *
 * Shared by task mode (Linsight execution flow) and daily-mode chat, so both
 * surfaces read identically. The `com_linsight_error_*` key prefix predates the
 * move and is kept — renaming ~20 keys across three locales would change nothing
 * a user sees.
 */
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { ServiceBusyNotice } from '~/components/ServiceBusyNotice';
import type { WorkbenchModelOption } from '~/components/Chat/ModelAvailabilityOption';

interface ChatErrorCardProps {
    /** stable classification from the backend (error_message event / SSE error `data.error_type`) */
    errorType?: string;
    /** raw provider text for the "view details" disclosure */
    detail?: string;
    /** legacy/raw error string — fallback when `detail` is absent */
    fallbackMessage?: string;
    /** transient (retryable) errors only: re-run the turn. Wired on the /linsight
        ExecutionFlow via continueConversation and on daily chat via regenerate;
        omitted on /c and history views. */
    onRetry?: () => void;
    retrying?: boolean;
    rateLimitState?: 'normal' | 'recovering' | 'busy';
    /** Fires the model switch with the id picked from the dropdown. */
    onSwitchModel?: (modelId: string) => void;
    /** Candidate models for the switch-model dropdown (pre-filtered). */
    switchModelOptions?: WorkbenchModelOption[];
    onLater?: () => void;
}

// error_type values that have their own localized copy; anything else (or a
// missing type from an older backend) falls back to the generic `unknown` set.
const KNOWN_TYPES = new Set([
    'content_filter',
    'quota_exhausted',
    'rate_limit',
    'service_unavailable',
    'network_timeout',
    'auth_error',
    // Attachment parsing (OCR / ETL) — daily-mode chat only.
    'file_parse_busy',
    'file_parse_failed',
    // Daily-mode counterpart of `unknown`: same card, wording that says "reply"
    // rather than "task" so a chat turn doesn't get task-mode phrasing.
    'chat_unknown',
]);

// Transient upstream hiccups (throttling / timeout / 5xx) recover on their own, so
// they get the calm neutral ServiceBusyNotice (+ optional retry) rather than the red
// failure card — a rate limit is the model vendor's availability blip, not a fault.
// Mirrors the classifier's RETRYABLE bucket.
//
// `file_parse_busy` is deliberately NOT here despite being recoverable: the turn is
// already lost (the attachment never made it into the prompt), so a Retry button
// would re-run against the same throttled service. It keeps its own "busy" wording
// but renders as the red card, and the user re-sends from the input box.
const TRANSIENT_TYPES = new Set([
    'rate_limit',
    'network_timeout',
    'service_unavailable',
]);

/** Would this failure render as the calm busy notice rather than the red card?
    Callers use it to decide whether to offer Retry and to suppress copy/feedback
    actions on a "try again" status. */
export function isTransientErrorType(errorType?: string): boolean {
    return !!errorType && TRANSIENT_TYPES.has(errorType);
}

export function ChatErrorCard({
    errorType,
    detail,
    fallbackMessage,
    onRetry,
    retrying,
    rateLimitState,
    onSwitchModel,
    switchModelOptions,
    onLater,
}: ChatErrorCardProps) {
    const localize = useLocalize();
    const [showDetail, setShowDetail] = useState(false);

    // Recovery rejected = the model is STILL rate-limited after a retry, so it
    // reads as the same busy notice: standard title, the backend's own copy as
    // the body, and the full retry / switch-model affordances kept available.
    if (errorType === 'recovery_rejected') {
        return (
            <ServiceBusyNotice
                title={localize('com_message.rate_limit_title')}
                desc={fallbackMessage || ''}
                onRetry={onRetry}
                retrying={retrying}
                onSwitchModel={onSwitchModel}
                switchModelOptions={switchModelOptions}
                onLater={onLater}
            />
        );
    }

    const key = errorType && KNOWN_TYPES.has(errorType) ? errorType : 'unknown';
    const title = localize(`com_linsight_error_title_${key}`);
    const desc = localize(`com_linsight_error_desc_${key}`);
    const hint = localize(`com_linsight_error_hint_${key}`);
    const rawDetail = detail || fallbackMessage || '';

    // Transient → calm neutral notice (with retry where the surface wires it).
    if (TRANSIENT_TYPES.has(key)) {
        const isRateLimit = key === 'rate_limit';
        return (
            <ServiceBusyNotice
                title={title}
                desc={desc}
                // The animated gauge is reserved for the rate-limit (service
                // load) family; timeout / unavailable are outages, so they get
                // the static gray attention mark.
                icon={isRateLimit ? 'gauge' : 'attention'}
                detail={isRateLimit ? undefined : rawDetail}
                onRetry={onRetry}
                retrying={retrying}
                rateLimitState={isRateLimit ? (rateLimitState ?? 'busy') : undefined}
                onSwitchModel={isRateLimit ? onSwitchModel : undefined}
                switchModelOptions={isRateLimit ? switchModelOptions : undefined}
                onLater={isRateLimit ? onLater : undefined}
            />
        );
    }

    // Terminal / unknown → the informative failure card. Same neutral surface
    // and text ramp as ServiceBusyNotice — the warning-orange is confined to
    // the icon, so a wall of failed turns doesn't read as a wall of color.
    return (
        <div className="my-2 rounded-2xl border border-border bg-bg-page p-4 text-sm">
            <div className="flex items-start gap-2.5">
                <Outlined.Attention size={16} className="mt-0.5 shrink-0 text-warning" />
                <div className="min-w-0 flex-1">
                    <div className="font-medium text-text-2">{title}</div>
                    <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed text-text-3">{desc}</p>
                    {hint && <p className="mt-1.5 leading-relaxed text-text-3">{hint}</p>}

                    {rawDetail && (
                        <div className="mt-2.5">
                            <button
                                type="button"
                                onClick={() => setShowDetail((v) => !v)}
                                className="inline-flex items-center gap-1 text-body text-gray-400 transition-colors hover:text-gray-600"
                            >
                                {localize(showDetail ? 'com_linsight_error_hide_detail' : 'com_linsight_error_view_detail')}
                                {showDetail ? <Outlined.Down size={14} /> : <Outlined.Right size={14} />}
                            </button>
                            {showDetail && (
                                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-100 p-2.5 text-xs leading-relaxed text-gray-500">
                                    {rawDetail}
                                </pre>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
