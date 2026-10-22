// @ts-strict-ignore
import { Tooltip as SharedTooltip } from '@bisheng/ui';
import { useState } from 'react';
import type { FC } from 'react';
import type { TConversationTag } from '~/types/chat';
import { OGDialogTrigger } from '~/components/ui';
import BookmarkEditDialog from './BookmarkEditDialog';
import { EditIcon } from '~/components/svg';
import { useLocalize } from '~/hooks';

const EditBookmarkButton: FC<{
  bookmark: TConversationTag;
  tabIndex?: number;
  onFocus?: () => void;
  onBlur?: () => void;
}> = ({ bookmark, tabIndex = 0, onFocus, onBlur }) => {
  const localize = useLocalize();
  const [open, setOpen] = useState(false);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      setOpen(!open);
    }
  };

  return (
    <BookmarkEditDialog
      context="EditBookmarkButton"
      bookmark={bookmark}
      open={open}
      setOpen={setOpen}
    >
      <SharedTooltip  content={localize('com_ui_edit')}  ><OGDialogTrigger asChild><div role="button" aria-label={localize('com_ui_bookmarks_edit')} tabIndex={tabIndex} onFocus={onFocus} onBlur={onBlur} onClick={() => setOpen(!open)} className="flex size-7 items-center justify-center rounded-lg transition-colors duration-200 hover:bg-surface-hover" onKeyDown={handleKeyDown}  ><EditIcon /></div></OGDialogTrigger></SharedTooltip>
    </BookmarkEditDialog>
  );
};

export default EditBookmarkButton;
