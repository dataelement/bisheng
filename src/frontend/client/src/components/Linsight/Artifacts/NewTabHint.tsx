/**
 * Marks a deliverable whose click LEAVES this page.
 *
 * Almost every artifact previews in place; an HTML report can't (a full HTML
 * document needs the sandboxed `/html` viewer), so it opens a new browser tab
 * instead. That difference used to be invisible until the tab appeared — and
 * because the row never came back, the file had no download entry at all. The
 * hint states the behaviour before the click; the download action in the row's
 * trailing rail is how you keep the file instead of just viewing it.
 *
 * A bare ↗ rather than the boxed external-link glyph: at 14px next to a file
 * name the box competes with the download icon in the rail, and the arrow alone
 * already carries the meaning.
 *
 * Renders nothing for in-place types, so callers can drop it into every row
 * without branching.
 */
import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { isHtmlArtifact, type ArtifactFile } from './artifactUtils';

interface NewTabHintProps {
    file: ArtifactFile;
    className?: string;
}

export function NewTabHint({ file, className }: NewTabHintProps) {
    const localize = useLocalize();
    if (!isHtmlArtifact(file)) return null;
    const label = localize('com_linsight_opens_in_new_tab');
    return (
        <span
            role="img"
            title={label}
            aria-label={label}
            className={cn('inline-flex shrink-0 items-center text-[#C0C4CC]', className)}
        >
            <Outlined.ArrowRightUp className="size-4" />
        </span>
    );
}
