import { AppChatFileChip, isAppChatImageFile } from './AppChatFileChip';
import type { AppChatFileLike } from '../appChatFileUtils';

interface AppChatFileListProps {
    files: AppChatFileLike[];
    className?: string;
}

/**
 * Attachment list for a workflow-chat message.
 *
 * Pictures and cards are laid out in separate rows because they are different
 * shapes — a 100px picture square next to a ~56px file card leaves a ragged
 * line when they share one wrap container. Daily mode splits them the same way.
 */
export function AppChatFileList({ files, className }: AppChatFileListProps) {
    if (!files?.length) return null;

    const images = files.filter(isAppChatImageFile);
    const others = files.filter((file) => !isAppChatImageFile(file));

    return (
        <div className={className}>
            {images.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {images.map((file, index) => (
                        <AppChatFileChip key={`img-${index}`} file={file} variant="message" />
                    ))}
                </div>
            )}
            {others.length > 0 && (
                <div className="mt-2 flex max-w-sm flex-wrap gap-2 first:mt-0">
                    {others.map((file, index) => (
                        <AppChatFileChip key={`file-${index}`} file={file} variant="message" />
                    ))}
                </div>
            )}
        </div>
    );
}
