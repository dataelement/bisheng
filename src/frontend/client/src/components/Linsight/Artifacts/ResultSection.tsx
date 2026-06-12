/**
 * F035 Track H (P4): final-result artifact delivery (spec §5, fig 8/12).
 * Rendered in the ExecutionFlow `execution-artifacts` slot once the run
 * completes: report link row → answer markdown → output files card.
 */
import { Eye, FileText } from 'lucide-react';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import FileIcon from '~/components/ui/icon/File';
import { useLocalize } from '~/hooks';
import '~/markdown.css';
import { type ArtifactFile, getFileExtension } from './artifactUtils';
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

            {/* output files card */}
            {files.length > 0 && (
                <div className="rounded-2xl border border-gray-200 bg-white p-3">
                    <div className="flex items-center gap-2 px-1 pb-2 text-sm font-medium text-gray-800">
                        <img
                            className="size-4"
                            src={`${__APP_ENV__.BASE_URL}/assets/lingsi.svg`}
                            alt=""
                        />
                        {localize('com_linsight_output_files', { 0: String(files.length) })}
                    </div>
                    <div className="space-y-0.5">
                        {files.map((file) => (
                            <div
                                key={file.file_id || file.file_url}
                                className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-gray-50"
                            >
                                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union */}
                                <FileIcon type={getFileExtension(file.file_name) as any} className="size-4 min-w-4" />
                                <span className="min-w-0 flex-1 truncate text-sm text-gray-800">
                                    {file.file_name}
                                </span>
                                <button
                                    type="button"
                                    aria-label={localize('com_linsight_preview')}
                                    className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100"
                                    onClick={() => onPreview(file)}
                                >
                                    <Eye size={15} />
                                </button>
                                <SaveAsButton file={file} versionId={versionId} />
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
