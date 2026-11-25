/**
 * F004 — a question the run asked in a daily answer, shown with the user's
 * answer. Same row as an answered clarify in deep research (IntentRow).
 */
import { useMemo } from 'react';
import { IntentRow } from '~/components/Linsight/Execution/IntentRow';
import { askedQuestionData, type ToolCallEvent } from './askedQuestion';

interface AskedQuestionRowProps {
    event: ToolCallEvent;
}

export function AskedQuestionRow({ event }: AskedQuestionRowProps) {
    const data = useMemo(() => askedQuestionData(event), [event]);
    return <IntentRow data={data} />;
}
