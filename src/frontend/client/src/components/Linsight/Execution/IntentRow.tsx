/**
 * F035 Track H (P3): "user intent confirmed" summary row (spec §2/§3).
 * Shown after a user_input request is answered (user_input_completed) —
 * expand to review the confirmed items (question -> answer pairs).
 */
import { Check } from 'lucide-react';
import { useLocalize } from '~/hooks';
import { StepRow, detailTextCls } from './StepRow';
import type { ExecStepEventData } from './stepUtils';
import { parseClarifyRequest } from './stepUtils';

export function IntentRow({ data }: { data: ExecStepEventData }) {
    const localize = useLocalize();
    const request = parseClarifyRequest(data);
    // answer text: locally stamped user_input (sendInput) or backend-replayed history
    const answer = data.user_input || '';

    return (
        <StepRow
            icon={<Check size={14} className="text-green-500" />}
            title={localize('com_linsight_intent_confirmed')}
            running={false}
        >
            {request.questions.length > 0 ? (
                <ol className="space-y-1">
                    {request.questions.map((q, i) => (
                        <li key={q.id} className="text-xs leading-5 text-gray-600">
                            {i + 1}. {q.question}
                        </li>
                    ))}
                </ol>
            ) : (
                request.callReason && <p className={detailTextCls}>{request.callReason}</p>
            )}
            {answer && <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-gray-800">{answer}</p>}
        </StepRow>
    );
}
