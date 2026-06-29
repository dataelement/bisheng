/**
 * F035 Track H (P3): "user intent confirmed" summary row (spec §2/§3).
 * Shown after a user_input request is answered (user_input_completed) —
 * expand to review the confirmed items (question -> answer pairs).
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { StepRow, detailTextCls } from './StepRow';
import { INK, MUTED } from './execTokens';
import type { ClarifyQuestion, ExecStepEventData } from './stepUtils';
import { CLARIFY_SKIP_SIGNAL, parseClarifyRequest } from './stepUtils';

export function IntentRow({ data }: { data: ExecStepEventData }) {
    const localize = useLocalize();
    const request = parseClarifyRequest(data);
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
        <StepRow
            // §2.4: Clap 16px, Ink hero glyph (hero-associated icon = Ink per §1.3).
            icon={<Outlined.Clap size={16} style={{ color: INK }} />}
            title={localize('com_linsight_intent_confirmed')}
            running={false}
        >
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
        </StepRow>
    );
}
