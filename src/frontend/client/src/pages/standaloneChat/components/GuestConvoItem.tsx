import { useState, useRef, useCallback, useEffect, useId } from 'react';
import { Check, X, Ellipsis, Pen, Trash } from 'lucide-react';
import * as Menu from '@ariakit/react/menu';
import type { MouseEvent, FocusEvent, KeyboardEvent } from 'react';

import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import type { AppConversation } from '~/@types/app';

import { DropdownPopup, OGDialog, Label } from '~/components';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import TodayItemIcon from '~/components/ui/icon/TodayItem';

type GuestConvoItemProps = {
  conv: AppConversation;
  isActive: boolean;
  onClick: () => void;
  onRename: (chatId: string, newTitle: string) => void;
  onDelete: (chatId: string) => void;
};

/**
 * Conversation list item for guest (no-login) mode.
 * Same UI as AppSidebarConvoItem but uses local callbacks instead of server mutations.
 */
export function GuestConvoItem({ conv, isActive, onClick, onRename, onDelete }: GuestConvoItemProps) {
  const localize = useLocalize();

  const [isPopoverActive, setIsPopoverActive] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [titleInput, setTitleInput] = useState(conv.title);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const menuId = useId();
  const deleteButtonRef = useRef<HTMLButtonElement>(null);

  // Rename logic
  const handleRenameStart = useCallback((e?: MouseEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    setIsPopoverActive(false);
    setTitleInput(conv.title);
    setRenaming(true);
  }, [conv.title]);

  useEffect(() => {
    if (renaming && inputRef.current) {
      inputRef.current.focus();
    }
  }, [renaming]);

  const submitRename = useCallback(
    (e: MouseEvent<HTMLButtonElement> | FocusEvent<HTMLInputElement> | KeyboardEvent<HTMLInputElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setRenaming(false);
      if (titleInput === conv.title || !titleInput) return;
      onRename(conv.id, titleInput);
    },
    [conv, titleInput, onRename],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Escape') {
        setTitleInput(conv.title);
        setRenaming(false);
      } else if (e.key === 'Enter') {
        submitRename(e);
      }
    },
    [conv.title, submitRename],
  );

  const cancelRename = useCallback(
    (e: MouseEvent<HTMLButtonElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setTitleInput(conv.title);
      setRenaming(false);
    },
    [conv.title],
  );

  const confirmDelete = useCallback(() => {
    onDelete(conv.id);
    setShowDeleteDialog(false);
  }, [conv.id, onDelete]);

  return (
    <div
      className={cn(
        'group relative w-full content-stretch flex gap-[8px] items-center mb-1 px-[12px] py-[6px] rounded-lg shrink-0 transition-colors cursor-pointer',
        isActive ? 'bg-[#e6edfc]' : 'hover:bg-[#f7f7f7]',
        renaming ? 'bg-[#e6edfc]' : '',
      )}
      onClick={(e) => {
        if (renaming || isPopoverActive || showDeleteDialog) return;
        onClick();
      }}
    >
      {renaming ? (
        <div className="flex h-6 grow cursor-pointer items-center gap-[8px] overflow-hidden whitespace-nowrap break-all">
          <input
            ref={inputRef}
            type="text"
            className="w-full rounded bg-white px-1 text-[14px] leading-tight focus-visible:outline-none text-[#212121]"
            value={titleInput ?? ''}
            onChange={(e) => setTitleInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onClick={(e) => e.stopPropagation()}
          />
          <div className="flex gap-1 shrink-0">
            <button onClick={cancelRename}>
              <X className="h-4 w-4 transition-colors duration-200 ease-in-out hover:opacity-70 text-[#4e5969]" />
            </button>
            <button onClick={submitRename}>
              <Check className="h-4 w-4 transition-colors duration-200 ease-in-out hover:opacity-70 text-[#165dff]" />
            </button>
          </div>
        </div>
      ) : (
        <div
          className="flex grow items-center gap-[8px] overflow-hidden whitespace-nowrap break-all"
          onDoubleClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            handleRenameStart();
          }}
        >
          <TodayItemIcon className="size-[24px] shrink-0 text-[#6B778D]" />
          <span className="text-[#212121] text-[14px] leading-[20px] font-['PingFang_SC:Regular',sans-serif] truncate">
            {conv.title}
          </span>
        </div>
      )}

      {/* Dropdown options */}
      <div
        className={cn(
          isPopoverActive || isActive
            ? 'flex'
            : 'hidden group-focus-within:flex group-hover:flex',
          'shrink-0 touch-mobile:flex [@media(hover:none)]:flex',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {!renaming && (
          <>
            <DropdownPopup
              isOpen={isPopoverActive}
              setIsOpen={setIsPopoverActive}
              trigger={
                <Menu.MenuButton
                  id={`guest-convo-menu-${conv.id}`}
                  className={cn(
                    'z-30 inline-flex h-4 w-4 items-center justify-center gap-2 rounded-md border-none p-0 text-sm font-medium transition-all duration-200 ease-in-out focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 text-[#86909c] hover:text-[#1d2129]',
                    isActive
                      ? 'opacity-100'
                      : 'opacity-0 focus:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 data-[open]:opacity-100 touch-mobile:opacity-100 [@media(hover:none)]:opacity-100',
                  )}
                >
                  <Ellipsis className="icon-md" aria-hidden={true} />
                </Menu.MenuButton>
              }
              items={[
                {
                  label: localize('com_ui_rename'),
                  onClick: handleRenameStart,
                  icon: <Pen className="icon-sm mr-2 text-text-primary" />,
                },
                {
                  label: localize('com_ui_delete'),
                  onClick: () => {
                    setIsPopoverActive(false);
                    setShowDeleteDialog(true);
                  },
                  icon: <Trash className="icon-sm mr-2 text-text-primary" />,
                  hideOnClick: false,
                  ref: deleteButtonRef,
                  render: (props) => <button {...props} />,
                },
              ]}
              menuId={menuId}
            />

            {/* Delete confirmation dialog */}
            {showDeleteDialog && (
              <OGDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog} triggerRef={deleteButtonRef}>
                <OGDialogTemplate
                  showCloseButton={false}
                  title={localize('com_ui_delete_conversation')}
                  className="max-w-[450px]"
                  main={
                    <div className="flex w-full flex-col items-center gap-2">
                      <div className="grid w-full items-center gap-2">
                        <Label className="text-left text-sm font-medium">
                          {localize('com_ui_delete_confirm')} <strong>{conv.title}</strong>
                        </Label>
                      </div>
                    </div>
                  }
                  selection={{
                    selectHandler: confirmDelete,
                    selectClasses: 'bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800 text-white',
                    selectText: localize('com_ui_delete'),
                  }}
                />
              </OGDialog>
            )}
          </>
        )}
      </div>
    </div>
  );
}
