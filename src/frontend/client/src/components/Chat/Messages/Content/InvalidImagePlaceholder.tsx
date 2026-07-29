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
        'flex h-[120px] w-[160px] flex-col items-center justify-center gap-2 rounded-lg',
        'border border-border-light bg-surface-secondary text-text-secondary',
        className,
      )}
    >
      <Outlined.FileImage className="size-7 opacity-60" />
      <span className="px-2 text-center text-xs leading-tight">
        {localize('com_chat_image_expired')}
      </span>
    </div>
  );
}
