/**
 * F035 Track H (P4): final-result artifact delivery (spec §5, fig 8/12).
 * Rendered in the ExecutionFlow `execution-artifacts` slot once the run
 * completes: report link row → answer markdown → output files card.
 */
import { Outlined } from 'bisheng-icons';
import { FileText } from 'lucide-react';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { useLocalize } from '~/hooks';
import '~/markdown.css';
import { type ArtifactFile } from './artifactUtils';
import { SaveAsButton } from './SaveAsButton';

interface ResultSectionProps {
    /** output_result.answer — the run summary, markdown */
    answer?: string;
    /** output_result.final_files (store file_list) */
    files: ArtifactFile[];
    versionId: string;
    onPreview: (file: ArtifactFile) => void;
}

export function ResultSection({ answer, files, versionId, onPreview }: ResultSectionProps) {
    const localize = useLocalize();
    // primary deliverable = first final file (spec §5: report link row)
    const primaryFile = files[0];

    return (
        <div className="space-y-3">
            {/* report link row */}
            {primaryFile && (
                <div className="flex items-center gap-1.5 text-sm text-gray-800">
                    <span className="shrink-0">{localize('com_linsight_report_ready')}</span>
                    <button
                        type="button"
                        className="flex min-w-0 items-center gap-1 text-blue-600 hover:underline"
                        onClick={() => onPreview(primaryFile)}
                    >
                        <FileText size={14} className="shrink-0" />
                        <span className="truncate">{primaryFile.file_name}</span>
                    </button>
                </div>
            )}

            {/* answer summary, markdown rendered */}
            {answer && (
                <div className="bs-mkdown rounded-2xl border border-gray-100 bg-white p-4 text-sm leading-6 text-gray-800">
                    <Markdown content={answer} isLatestMessage={true} webContent={false} />
                </div>
            )}

            {/* output files card — dotted background matching ClarifyCard */}
            {files.length > 0 && (
                <div
                    className="rounded-2xl border border-[#EEF2F6] p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]"
                    style={{
                        backgroundImage:
                            'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
                        backgroundSize: '5px 5px',
                        backgroundColor: '#fff',
                    }}
                >
                    {/* header: icon + title + count badge */}
                    <div className="flex items-center gap-2 pb-4">
                        <img
                            className="size-5"
                            src={`${__APP_ENV__.BASE_URL}/assets/lingsi.svg`}
                            alt=""
                        />
                        <span className="text-[14px] font-medium text-[#212121]">
                            {localize('com_linsight_output_files', { 0: String(files.length) })}
                        </span>
                    </div>

                    {/* file list */}
                    <div className="space-y-1">
                        {files.map((file) => (
                            <div
                                key={file.file_id || file.file_url}
                                className="flex items-center justify-between rounded-lg px-1 py-2.5"
                            >
                                <button
                                    type="button"
                                    className="min-w-0 flex-1 truncate text-left text-[14px] text-[#1A1A1A] hover:text-[#335CFF] transition-colors"
                                    onClick={() => onPreview(file)}
                                >
                                    {file.file_name}
                                </button>
                                <div className="flex shrink-0 items-center gap-1">
                                    <button
                                        type="button"
                                        aria-label={localize('com_linsight_preview')}
                                        className="rounded-md p-1 text-[#8C8C8C] hover:text-[#335CFF] transition-colors"
                                        onClick={() => onPreview(file)}
                                    >
                                        <Outlined.BookOpenText className="size-[18px]" />
                                    </button>
                                    <SaveAsButton file={file} versionId={versionId} />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
