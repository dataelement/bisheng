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
import { useLocalize } from '~/hooks';
import { FailureInfoDetails } from '~/components/FailureInfoDetails';
import { localizedBusinessFailure, parseFailureInfo } from '~/utils/failureInfo';
import { ServiceBusyNotice } from '~/components/ServiceBusyNotice';
import type { WorkbenchModelOption } from '~/components/Chat/ModelAvailabilityOption';

interface ChatErrorCardProps {
    /** stable classification from the backend (error_message event / SSE error `data.error_type`) */
    errorType?: string;
    errorCode?: number;
    failureInfo?: unknown;
    /** raw provider text for the "view details" disclosure */
    detail?: string;
    /** legacy/raw error string — fallback when `detail` is absent */
    fallbackMessage?: string;
    /** transient (retryable) errors only: re-run the turn. Wired on the /linsight
        ExecutionFlow via continueConversation and on daily chat via regenerate;
        omitted on /c and history views. */
    onRetry?: () => void;
    /** disables the retry button + spins its icon while a retry is in flight */
    retrying?: boolean;
    rateLimitState?: 'normal' | 'recovering' | 'busy';
    /** Fires the model switch with the id picked from the dropdown. */
    onSwitchModel?: (modelId: string) => void;
    /** Candidate models for the switch-model dropdown (pre-filtered). */
    switchModelOptions?: WorkbenchModelOption[];
    onLater?: () => void;
    /** Replaces the per-type description on the failure card. Daily chat uses it
        when a stream fails *after* emitting an answer: the specific reason is noise,
        what matters is that the reply above is cut short. */
    description?: string;
    /** Drops the per-type "建议…" line. Daily chat sets it when the card carries a
        plain backend message as its description — a hint would just repeat it. */
    hideHint?: boolean;
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
    // Task mode only: the model spent its whole output budget (usually on
    // reasoning) without a tool call or an answer, even after one retry.
    'output_truncated',
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
    errorCode,
    failureInfo,
    onRetry,
    retrying,
    rateLimitState,
    onSwitchModel,
    switchModelOptions,
    onLater,
    description,
    hideHint,
}: ChatErrorCardProps) {
    const localize = useLocalize();
    const failure = rateLimitState === 'recovering' || rateLimitState === 'normal' ? undefined : parseFailureInfo(failureInfo);

    // Recovery rejected = the model is STILL rate-limited after a retry, so it
    // reads as the same busy notice: standard title, the backend's own copy as
    // the body, and the full retry / switch-model affordances kept available.
    if (!failure && errorType === 'recovery_rejected') {
        return (
            <ServiceBusyNotice
                title={localize('com_message.rate_limit_title')}
                desc={localize('com_message.rate_limit_busy_desc')}
                onRetry={onRetry}
                retrying={retrying}
                onSwitchModel={onSwitchModel}
                switchModelOptions={switchModelOptions}
                onLater={onLater}
            />
        );
    }

    const key = errorType && KNOWN_TYPES.has(errorType) ? errorType : 'unknown';
    const title = failure ? localize(`api_errors.failure_${failure.category}`) : localize(`com_linsight_error_title_${key}`);
    const desc = failure ? '' : localizedBusinessFailure(errorCode, localize) ?? description ?? localize(`com_linsight_error_desc_${key}`);
    const hint = failure || hideHint ? '' : localize(`com_linsight_error_hint_${key}`);


    // Transient → calm neutral notice (with retry where the surface wires it).
    if (TRANSIENT_TYPES.has(key)) {
        const isRateLimit = key === 'rate_limit';
        return (
            <ServiceBusyNotice
                title={title}
                desc={desc}
                failureInfo={failure}
                // The animated gauge is reserved for the rate-limit (service
                // load) family; timeout / unavailable are outages, so they get
                // the static gray attention mark.
                icon={isRateLimit ? 'gauge' : 'attention'}
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
                    {desc && <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed text-text-3">{desc}</p>}
                    <FailureInfoDetails failureInfo={failure} />
                    {hint && <p className="mt-1.5 leading-relaxed text-text-3">{hint}</p>}


                </div>
            </div>
        </div>
    );
}
