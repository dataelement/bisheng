/**
 * F035 Track H (P3): "user intent confirmed" summary row (spec §2/§3).
 * Shown after a user_input request is answered (user_input_completed) —
 * expand to review the confirmed items (question -> answer pairs).
 *
 * Layout mirrors DeepStepGroup (NOT the rail-based StepRow) so this node lines
 * up with the "已深度思考" node: icon + title + chevron form ONE group with 4px
 * (py-1) padding, the whole node carries 12px (pb-3) below, and the expanded body
 * is indented pl-6 under the title.
 */
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { detailTextCls } from './StepRow';
import { INK, MUTED } from './execTokens';
import type { ClarifyQuestion, ExecStepEventData } from './stepUtils';
import { CLARIFY_SKIP_SIGNAL, parseClarifyRequest } from './stepUtils';

export function IntentRow({ data }: { data: ExecStepEventData }) {
    const localize = useLocalize();
    const request = parseClarifyRequest(data);
    // Confirmed summary defaults collapsed (history review); one click expands.
    const [open, setOpen] = useState(false);
    // answer text: locally stamped user_input (sendInput) or backend-replayed history.
    // composed as `${question}: ${answer}` per line for multi-question (see
    // composeClarifyAnswer); pair each question with its answer line by index.
    const answer = data.user_input || '';
    const answerLines = answer ? answer.split('\n') : [];
    const answerFor = (q: ClarifyQuestion, i: number): string => {
        const line = answerLines[i] ?? '';
        if (request.questions.length > 1 && line.startsWith(q.question)) {
            return line.slice(q.question.length).replace(/^\s*[:：]\s*/, '');
        }
        return line;
    };

    return (
        <div className="w-full min-w-0 pb-3 animate-thinking-appear">
            {/* Header group: icon + title + chevron in one py-1 row (matches DeepStepGroup). */}
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="group flex w-full items-center gap-2 py-1 text-left text-sm font-medium leading-[22px]"
                style={{ color: '#999999' }}
            >
                <span className="flex size-4 shrink-0 items-center justify-center">
                    {/* §2.4: Clap 16px, Ink hero glyph. */}
                    <Outlined.Clap size={16} style={{ color: INK }} />
                </span>
                <span
                    className={cn(
                        'min-w-0 truncate transition-colors group-hover:text-[#212121]',
                        open && 'text-[#212121]',
                    )}
                >
                    {localize('com_linsight_intent_confirmed')}
                </span>
                {/* Single chevron rotates right→down (collapsed → expanded); muted,
                    darkening on hover — same as DeepStepGroup / StepRow. */}
                <Outlined.Down
                    size={16}
                    className={cn(
                        'shrink-0 transform-gpu text-[#8C8C8C] transition duration-200 group-hover:text-[#212121]',
                        !open && '-rotate-90',
                    )}
                />
            </button>
            <div
                className={cn('grid transition-all duration-300 ease-out', open && 'mt-2')}
                style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
            >
                <div className="min-h-0 overflow-hidden">
                    <div className="pl-6">
                        {request.questions.length > 0 ? (
                            <ol className="space-y-2">
                                {request.questions.map((q, i) => {
                                    const ans = answerFor(q, i);
                                    return (
                                        <li key={q.id} className="text-xs leading-5">
                                            {/* question: Ink, shown once; answer: Muted, trailing (§2.4 color regime) */}
                                            <span className="font-medium" style={{ color: INK }}>
                                                {i + 1}. {q.question}
                                            </span>
                                            {ans && <span className="ml-3" style={{ color: MUTED }}>{ans}</span>}
                                        </li>
                                    );
                                })}
                            </ol>
                        ) : (
                            <>
                                {request.callReason && <p className={detailTextCls}>{request.callReason}</p>}
                                {answer && (
                                    <p className="whitespace-pre-wrap text-xs leading-5" style={{ color: MUTED }}>
                                        {/* fallback-card skip: show a friendly "已跳过" instead of the raw sentinel */}
                                        {answer === CLARIFY_SKIP_SIGNAL ? localize('com_linsight_clarify_skip_answer') : answer}
                                    </p>
                                )}
                            </>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
