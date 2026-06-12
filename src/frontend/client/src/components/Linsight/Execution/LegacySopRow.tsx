import { FileText } from 'lucide-react';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { useLocalize } from '~/hooks';
import { StepRow } from './StepRow';
import '~/markdown.css';

/**
 * Read-only viewer for the legacy SOP document on pre-F035 sessions.
 * The SOP concept is gone from the new pipeline, but historical sessions
 * still carry their generated SOP markdown — show it collapsed, rendered
 * with the shared react-markdown component (vditor was removed).
 */
export function LegacySopRow({ sop }: { sop?: string | null }) {
    const localize = useLocalize();
    const content = sop?.trim();
    if (!content) return null;

    return (
        <StepRow
            icon={<FileText size={15} className="text-gray-400" />}
            title={localize('com_linsight_legacy_sop')}
            titleClassName="text-gray-500"
        >
            <div className="bs-mkdown rounded-xl border border-gray-100 bg-white p-4 text-sm leading-6 text-gray-700">
                <Markdown content={content} isLatestMessage={false} webContent={false} />
            </div>
        </StepRow>
    );
}
