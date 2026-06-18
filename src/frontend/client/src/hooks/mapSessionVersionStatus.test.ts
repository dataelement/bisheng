import { mapSessionVersionStatus } from './useLinsightManager';
import { SopStatus } from '~/store/linsight';

describe('mapSessionVersionStatus', () => {
    it('maps in_progress to Running', () => {
        expect(mapSessionVersionStatus('in_progress')).toBe(SopStatus.Running);
    });

    // Regression: after a refresh, a session parked on an ask_user interrupt must
    // still be treated as Running so the ClarifyCard / waiting input re-renders.
    // Previously `waiting_for_user_input` fell through to the default branch and
    // stayed the raw string, making `running` false and hiding the input prompt.
    it('maps waiting_for_user_input to Running (HITL park-and-release survives reload)', () => {
        expect(mapSessionVersionStatus('waiting_for_user_input')).toBe(SopStatus.Running);
    });

    // Regression: a queued task sits at backend status `not_started` until the
    // worker dequeues it (then -> in_progress). The F035 client has no manual
    // start step, so not_started == queued and must map to Running, otherwise the
    // 排队中 QueueCard / queue polling is lost on refresh or session switch.
    it('maps not_started (queued) to Running', () => {
        expect(mapSessionVersionStatus('not_started')).toBe(SopStatus.Running);
    });

    it('maps sop_generation_failed to SopGenerated', () => {
        expect(mapSessionVersionStatus('sop_generation_failed')).toBe(SopStatus.SopGenerated);
    });

    it('maps completed to completed, or FeedbackCompleted when feedback exists', () => {
        expect(mapSessionVersionStatus('completed')).toBe(SopStatus.completed);
        expect(mapSessionVersionStatus('completed', 'great')).toBe(SopStatus.FeedbackCompleted);
    });

    it('maps terminated / failed to Stoped', () => {
        expect(mapSessionVersionStatus('terminated')).toBe(SopStatus.Stoped);
        expect(mapSessionVersionStatus('failed')).toBe(SopStatus.Stoped);
    });

    it('passes unknown statuses through unchanged', () => {
        expect(mapSessionVersionStatus('something_new')).toBe('something_new');
    });
});
