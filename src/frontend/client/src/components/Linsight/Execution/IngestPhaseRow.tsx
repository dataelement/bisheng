/**
 * IngestPhaseRow — the attachment-ingest phase, rendered as PREPARATION rather
 * than as an agent tool call.
 *
 * Deferring the ingest into the worker moved a multi-minute parse (12 bid PDFs
 * measured at ~20 min) into the visible timeline. It first shipped through the
 * generic tool row, which was wrong three ways at once:
 *
 *  1. **Vocabulary.** "已使用 ingest_uploads" names an internal function. The user
 *     uploaded attachments; that is what the row must talk about.
 *  2. **Attribution.** As a tool row it counted into the group's activity tally,
 *     so the system's parse time was billed to the agent's thinking — the header
 *     read "执行 1 步操作（用时 1416 秒）" and the product looked catastrophically
 *     slow when it was simply parsing a lot of paper. (Fixed in activity.ts.)
 *  3. **Silence.** `done/total` and the current filename were already on the wire
 *     in `extra_info.ingest_progress` and nothing rendered them, so twenty minutes
 *     passed with a static line — indistinguishable from a hang.
 *
 * So this row leads with the COUNT (the only phase of a run with a true a-priori
 * denominator) and carries the current filename underneath. No duration: a
 * stopwatch measures how long you have waited, never how much is left, and the
 * whole surface dropped elapsed-time headers for that reason.
 */
import { Outlined } from 'bisheng-icons';
import type { FC } from 'react';
import { useLocalize } from '~/hooks';
import { ACCENT, MUTED } from './execTokens';
import { INGEST_PHASE_I18N, readIngestProgress } from './execTypes';
import { NarrationTicker } from './NarrationTicker';
import type { MergedStep } from './stepUtils';

export interface IngestPhaseRowProps {
    step: MergedStep;
}

export const IngestPhaseRow: FC<IngestPhaseRowProps> = ({ step }) => {
    const localize = useLocalize();
    const progress = readIngestProgress(step);
    // Defensive: callers gate on the same predicate, but an older worker emits the
    // step name with no payload — falling through to nothing beats rendering a row
    // that says "undefined/undefined".
    if (!progress) return null;

    const running = progress.phase === 'running';
    const title = localize(INGEST_PHASE_I18N[progress.phase], {
        0: String(progress.done),
        1: String(progress.total),
    });

    return (
        <div className="flex w-full min-w-0 gap-2 py-1">
            <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                {running ? (
                    <Outlined.Loading size={16} className="animate-spin" style={{ color: ACCENT }} />
                ) : (
                    // A file glyph, not the generic tool wrench: the icon is the
                    // fastest signal that this row is about the user's uploads.
                    <Outlined.File size={16} style={{ color: MUTED }} />
                )}
            </span>
            <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm" style={{ color: MUTED }}>
                    {title}
                </span>
                {/* The moving part. NarrationTicker owns the one-line-at-a-time
                    crossfade + reduced-motion handling; reusing it keeps this line
                    behaving exactly like the reasoning aside above it. Failure text
                    rides `output` and takes the same slot, since a failed ingest
                    ends the run and the reason has to be readable inline. */}
                <NarrationTicker text={running ? progress.fileName || '' : step.output || ''} />
            </div>
        </div>
    );
};

IngestPhaseRow.displayName = 'IngestPhaseRow';

export default IngestPhaseRow;
