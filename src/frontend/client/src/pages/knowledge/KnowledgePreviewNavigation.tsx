import { Outlined } from 'bisheng-icons';
import { ChevronRight, X } from 'lucide-react';
import { isDesktopEmbedded } from '~/components/Chat/desktopEmbedding';
import { Button } from '~/components/ui/Button';
import { useLocalize, usePrefersMobileLayout } from '~/hooks';

interface KnowledgePreviewNavigationProps {
    onClose: () => void;
}

/** Embedded previews fill the host content area, so expose the return action at the top. */
export function KnowledgePreviewNavigation({ onClose }: KnowledgePreviewNavigationProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    if (isDesktopEmbedded()) {
        return (
            // Align the leading icon with the shared content gutter; keep Button sizing intact.
            <div className="-ml-4 shrink-0 pt-4">
                <Button color="default" variant="text" size="medium" onClick={onClose}>
                    <Outlined.ArrowLeft />
                    {localize('com_ui_go_back')}
                </Button>
            </div>
        );
    }
    return isH5 ? (
        <button
            type="button"
            aria-label={localize('com_knowledge.close')}
            onClick={onClose}
            className="absolute right-4 top-4 z-20 inline-flex size-8 items-center justify-center rounded-md text-text-2 hover:bg-fill-1"
        >
            <X className="size-4" />
        </button>
    ) : (
        <button
            type="button"
            aria-label={localize('com_knowledge.collapse_drawer')}
            onClick={onClose}
            className="absolute left-1 top-1/2 z-20 flex h-16 w-6 -translate-y-1/2 items-center justify-center bg-white text-text-4 hover:text-text-3"
        >
            <ChevronRight className="size-6 stroke-[2.75]" />
        </button>
    );
}
