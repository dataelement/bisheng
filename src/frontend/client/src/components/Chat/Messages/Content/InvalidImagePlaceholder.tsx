import { Outlined } from 'bisheng-icons';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

/**
 * Stands in for an attachment whose bytes are no longer retrievable — an
 * upload from before attachments were made permanent, or one the storage
 * cleared. It keeps the message's shape instead of leaving a broken image, and
 * says why so the user doesn't take it for a loading failure worth retrying.
 */
export function InvalidImagePlaceholder({
  className,
  ...rest
}: { className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  const localize = useLocalize();

  return (
    <div
      {...rest}
      className={cn(
        // pt against a centered stack nudges it down by half the padding — 6px
        // here, enough to sit off dead-center without looking misaligned.
        'flex size-[100px] flex-col items-center justify-center gap-2 rounded-lg pt-3',
        // Same tint as the thumbnail it stands in for, and no border: in a row
        // of pictures the missing one should hold the place quietly rather than
        // draw a frame around itself.
        'bg-[#F8F8F8] text-text-3/60',
        className,
      )}
    >
      <Outlined.FileImage className="size-5" />
      {/* pre-line so a translation can place its own break; zh splits the two
          clauses onto their own lines rather than letting 100px decide. */}
      <span className="whitespace-pre-line px-2 text-center text-caption leading-tight">
        {localize('com_chat_image_expired')}
      </span>
    </div>
  );
}
