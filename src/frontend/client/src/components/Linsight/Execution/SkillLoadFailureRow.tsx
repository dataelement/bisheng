/**
 * SkillLoadFailureRow — a skill the user picked was not available for this run.
 *
 * Skill bundles are fetched from object storage when a run starts. If that fails
 * the task still proceeds, just without the skill; the model then behaves exactly
 * as if the skill had never been selected. That silence is the actual defect this
 * row exists to close — under the previous node-local storage, a worker on a
 * different host found no bundle at all and the only trace was one warning in a
 * log nobody reads.
 *
 * Renders as preparation (like the ingest row), not as an agent tool call: the
 * agent did not do this, and it must not count toward the group's activity tally.
 */
import { Outlined } from 'bisheng-icons';
import type { FC } from 'react';
import { useLocalize } from '~/hooks';
import { MUTED } from './execTokens';
import { readSkillLoadFailure } from './execTypes';
import type { MergedStep } from './stepUtils';

export interface SkillLoadFailureRowProps {
    step: MergedStep;
}

export const SkillLoadFailureRow: FC<SkillLoadFailureRowProps> = ({ step }) => {
    const localize = useLocalize();
    const names = readSkillLoadFailure(step);
    // Defensive: an older worker can emit the name with no payload.
    if (!names) return null;

    return (
        <div className="flex w-full min-w-0 gap-2 py-1">
            <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                <Outlined.Info size={16} style={{ color: MUTED }} />
            </span>
            <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm" style={{ color: MUTED }}>
                    {localize('com_linsight_skill_load_failed', { 0: names.join('、') })}
                </span>
            </div>
        </div>
    );
};

SkillLoadFailureRow.displayName = 'SkillLoadFailureRow';

export default SkillLoadFailureRow;
