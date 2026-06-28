/**
 * F035 Track H: ima-style FALLBACK clarify card.
 *
 * Rendered by ClarifyCard ONLY when parseClarifyRequest yields zero structured
 * questions — the ask_user "parse-failure" degrade that previously fell to a bare
 * textarea ("请输入…" with no guidance). Instead of an empty box it prints whatever
 * text is available (the model's `reason`/call_reason, which may carry prose
 * questions, verbatim with line breaks) and offers two clear exits:
 *   - 跳过，开始任务 → submit CLARIFY_SKIP_SIGNAL so the agent proceeds with defaults.
 *   - 补充信息       → reveal an inline textarea for free-form supplementary text.
 *
 * No interactive option selection. The structured interactive ClarifyCard path is
 * unchanged and only runs when there ARE parseable questions.
 */
import { useMemo, useState } from 'react';
import { Textarea } from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { ExecStepEventData } from './stepUtils';
import { CLARIFY_SKIP_SIGNAL, parseClarifyRequest } from './stepUtils';

interface ClarifyFallbackCardProps {
    data: ExecStepEventData;
    disabled?: boolean;
    /** submit the answer; rides the existing user-input API upstream (opaque text) */
    onSubmit: (taskId: string, answer: string) => void;
}

export function ClarifyFallbackCard({ data, disabled = false, onSubmit }: ClarifyFallbackCardProps) {
    const localize = useLocalize();
    const request = useMemo(() => parseClarifyRequest(data), [data]);

    const [showSupplement, setShowSupplement] = useState(false);
    const [text, setText] = useState('');
    const [submitted, setSubmitted] = useState(false);

    const finish = (answer: string) => {
        if (disabled || submitted || !answer) return;
        setSubmitted(true);
        onSubmit(request.taskId, answer);
    };
    const handleSkip = () => finish(CLARIFY_SKIP_SIGNAL);
    const handleSupplement = () => finish(text.trim());

    return (
        <div
            className="my-3 w-full rounded-2xl border border-[#EEF2F6] bg-white p-4 shadow-[0_4px_20px_rgba(0,0,0,0.03)]"
            style={{
                backgroundImage:
                    'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
                backgroundSize: '5px 5px',
            }}
        >
            {/* Intro / question text — printed verbatim so prose questions (with their
                own numbering / line breaks) render all at once. */}
            <p className="whitespace-pre-wrap break-words text-[15px] leading-6 text-[#212121]">
                {request.callReason || localize('com_linsight_clarify_title')}
            </p>

            {/* Supplement: inline textarea, revealed on demand (user's chosen entry point). */}
            {showSupplement && (
                <Textarea
                    autoFocus
                    value={text}
                    disabled={disabled || submitted}
                    rows={3}
                    maxLength={10000}
                    placeholder={localize('com_linsight_clarify_input_placeholder')}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                        // Enter submits; Shift+Enter inserts a newline; IME candidate-commit
                        // (isComposing) never submits prematurely.
                        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                            e.preventDefault();
                            handleSupplement();
                        }
                    }}
                    className="mt-3 resize-none text-sm rounded-xl border-none shadow-none bg-[#F5F7FA] placeholder:text-[#8C8C8C] focus-visible:ring-0 focus-visible:outline-none"
                />
            )}

            {/* Footer: always exactly two buttons — light Skip + dark action (ima style). */}
            <div className="mt-4 flex items-center gap-3">
                <button
                    type="button"
                    disabled={disabled || submitted}
                    onClick={handleSkip}
                    className="h-10 flex-1 rounded-xl bg-[#F5F7FA] text-sm font-medium text-[#212121] hover:bg-[#EEF0F4] disabled:opacity-50 transition-colors"
                >
                    {localize('com_linsight_clarify_skip_start')}
                </button>
                {showSupplement ? (
                    <button
                        type="button"
                        disabled={disabled || submitted || !text.trim()}
                        onClick={handleSupplement}
                        className="h-10 flex-1 rounded-xl bg-[#212121] text-sm font-medium text-white hover:bg-black disabled:opacity-50 transition-colors"
                    >
                        {localize('com_linsight_clarify_submit')}
                    </button>
                ) : (
                    <button
                        type="button"
                        disabled={disabled || submitted}
                        onClick={() => setShowSupplement(true)}
                        className="h-10 flex-1 rounded-xl bg-[#212121] text-sm font-medium text-white hover:bg-black disabled:opacity-50 transition-colors"
                    >
                        {localize('com_linsight_clarify_supplement')}
                    </button>
                )}
            </div>
        </div>
    );
}
