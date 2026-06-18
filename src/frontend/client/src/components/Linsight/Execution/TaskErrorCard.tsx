/**
 * Friendly, classified task-failure card (灵思LLM容错与失败态友好交互).
 *
 * Replaces the old red box that dumped the raw provider error (e.g. an English
 * aliyun "inappropriate content" message + a doc URL) on end users. The backend
 * ships a stable `error_type` (content_filter / quota_exhausted / network_timeout
 * …) on the error_message event; this card renders a localized title +
 * explanation + actionable hint per type, and keeps the raw provider text behind
 * a "view details" disclosure. Display-only — no retry action (the user re-runs
 * by asking again in the input).
 */
import { ChevronDown, ChevronRight, CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { useLocalize } from '~/hooks';

interface TaskErrorCardProps {
    /** stable classification from the backend (error_message event) */
    errorType?: string;
    /** raw provider text for the "view details" disclosure */
    detail?: string;
    /** legacy/raw taskError string — fallback when `detail` is absent */
    fallbackMessage?: string;
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
]);

export function TaskErrorCard({ errorType, detail, fallbackMessage }: TaskErrorCardProps) {
    const localize = useLocalize();
    const [showDetail, setShowDetail] = useState(false);

    const key = errorType && KNOWN_TYPES.has(errorType) ? errorType : 'unknown';
    const title = localize(`com_linsight_error_title_${key}`);
    const desc = localize(`com_linsight_error_desc_${key}`);
    const hint = localize(`com_linsight_error_hint_${key}`);
    const rawDetail = detail || fallbackMessage || '';

    return (
        <div className="my-2 rounded-xl border border-red-100 bg-red-50/60 p-4 text-sm">
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
