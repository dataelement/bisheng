/** @jest-environment node */

import { SopStatus, type LinsightInfo } from '~/store/linsight';
import { getContinueFailureUpdate } from './linsightContinueHelpers';

const failedRound = {
    id: 'version-1',
    question: 'Analyze gold trend',
    status: SopStatus.Stoped,
    taskError: 'rate limited',
    taskErrorInfo: { error_type: 'rate_limit', model_id: '18' },
    tasks: [{ id: 'task-1' }],
    sessionSteps: [{ call_id: 'step-1' }],
    output_result: { error_type: 'rate_limit' },
    file_list: [],
    history: [],
} as unknown as LinsightInfo;

describe('continueConversation failure state', () => {
    it('restores the complete failed round when switch-and-retry is rejected', () => {
        expect(getContinueFailureUpdate(failedRound, '22', new Error('model unavailable'))).toEqual({
            history: failedRound.history,
            question: failedRound.question,
            tasks: failedRound.tasks,
            sessionSteps: failedRound.sessionSteps,
            output_result: failedRound.output_result,
            file_list: failedRound.file_list,
            taskError: failedRound.taskError,
            taskErrorInfo: failedRound.taskErrorInfo,
            status: failedRound.status,
        });
    });

    it('preserves the legacy plain-retry failure update', () => {
        expect(
            getContinueFailureUpdate(failedRound, undefined, new Error('queue unavailable')),
        ).toEqual({
            status: SopStatus.Stoped,
            taskError: 'Error: queue unavailable',
        });
    });
});
