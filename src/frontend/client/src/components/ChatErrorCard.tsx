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
import { ChevronDown, ChevronRight, CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { ServiceBusyNotice } from '~/components/ServiceBusyNotice';

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

export function ChatErrorCard({ errorType, detail, fallbackMessage, onRetry }: ChatErrorCardProps) {
    const localize = useLocalize();
    const [showDetail, setShowDetail] = useState(false);

    const key = errorType && KNOWN_TYPES.has(errorType) ? errorType : 'unknown';
    const title = localize(`com_linsight_error_title_${key}`);
    const desc = localize(`com_linsight_error_desc_${key}`);
    const hint = localize(`com_linsight_error_hint_${key}`);
    const rawDetail = detail || fallbackMessage || '';

    // Transient → calm neutral notice (with retry where the surface wires it).
    if (TRANSIENT_TYPES.has(key)) {
        return <ServiceBusyNotice title={title} desc={desc} detail={rawDetail} onRetry={onRetry} />;
    }

    // Terminal / unknown → the informative (red) failure card.
    return (
        <div className="my-2 rounded-2xl border border-red-100 bg-red-50/60 p-4 text-sm">
            <div className="flex items-start gap-2.5">
                <CircleAlert size={18} className="mt-0.5 shrink-0 text-red-500" />
                <div className="min-w-0 flex-1">
                    <div className="font-medium text-red-700">{title}</div>
                    <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed text-red-600/90">{desc}</p>
                    {hint && <p className="mt-1.5 leading-relaxed text-red-600/80">{hint}</p>}

                    {rawDetail && (
                        <div className="mt-3">
                            <button
                                type="button"
                                onClick={() => setShowDetail((v) => !v)}
                                className="inline-flex items-center gap-1 text-xs text-red-600/70 transition-colors hover:text-red-700"
                            >
                                {showDetail ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                {localize(showDetail ? 'com_linsight_error_hide_detail' : 'com_linsight_error_view_detail')}
                            </button>
                            {showDetail && (
                                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-red-100/50 p-2.5 text-xs leading-relaxed text-red-700/80">
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
