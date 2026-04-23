import type { ConversationListResponse } from '~/types/chat';
import { PermissionTypes, Permissions } from '~/types/chat';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchContext } from '~/Providers';
import { Conversations } from '~/components/Conversations';
import { Spinner } from '~/components/svg';
import { useConversationsInfiniteQuery } from '~/hooks/queries/data-provider';
import {
  useAuthContext,
  useHasAccess,
  useLocalStorage,
  useLocalize,
  usePrefersMobileLayout,
  useNavScrolling,
} from '~/hooks';
import { cn } from '~/utils';
import AccountSettings from './AccountSettings';
import NavToggle from './NavToggle';
import NewChat from './NewChat';
import { ChatNavUserFooter } from './ChatNavUserFooter';

const Nav = ({
  navVisible,
  setNavVisible,
}: {
  navVisible: boolean;
  setNavVisible: React.Dispatch<React.SetStateAction<boolean>>;
}) => {
  const localize = useLocalize();
  const { isAuthenticated } = useAuthContext();

  const [navWidth, setNavWidth] = useState('260px');
  const [isHovering, setIsHovering] = useState(false);
  const isSmallScreen = usePrefersMobileLayout();
  const [newUser, setNewUser] = useLocalStorage('newUser', true);

  const hasAccessToBookmarks = useHasAccess({
    permissionType: PermissionTypes.BOOKMARKS,
    permission: Permissions.USE,
  });

  useEffect(() => {
    if (isSmallScreen) {
      const savedNavVisible = localStorage.getItem('navVisible');
      if (savedNavVisible === null) {
        toggleNavVisible();
      }
      // 移动端：与其它页面抽屉统一固定宽度
      setNavWidth('240px');
    } else {
      setNavWidth('240px');
    }
  }, [isSmallScreen]);

  const [showLoading, setShowLoading] = useState(false);

  const { pageNumber, searchQuery, setPageNumber, searchQueryRes } = useSearchContext();
  const [tags, setTags] = useState<string[]>([]);
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useConversationsInfiniteQuery(
      {
        pageNumber: pageNumber.toString(),
        isArchived: false,
        tags: tags.length === 0 ? undefined : tags,
      },
      { enabled: isAuthenticated },
    );

  useEffect(() => {
    // When a tag is selected, refetch the list of conversations related to that tag
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tags]);
  const { containerRef, moveToTop } = useNavScrolling<ConversationListResponse>({
    setShowLoading,
    hasNextPage: searchQuery ? searchQueryRes?.hasNextPage : hasNextPage,
    fetchNextPage: searchQuery ? searchQueryRes?.fetchNextPage : fetchNextPage,
    isFetchingNextPage: searchQuery
      ? searchQueryRes?.isFetchingNextPage ?? false
      : isFetchingNextPage,
  });

  const conversations = useMemo(
    () =>
      // 初始化列表or搜索数据获取
      (searchQuery ? searchQueryRes?.data : data)?.pages.flatMap((page) => page.conversations) ||
      [],
    [data, searchQuery, searchQueryRes?.data],
  );

  const toggleNavVisible = () => {
    setNavVisible((prev: boolean) => !prev);
    if (newUser) {
      setNewUser(false);
    }
  };

  const itemToggleNav = () => {
    if (isSmallScreen) {
      toggleNavVisible();
    }
  };

  return (
    <>
      <div
        data-testid="nav"
        className={cn(
          'nav active max-w-[240px] touch-mobile:max-w-none flex-shrink-0 overflow-x-hidden touch-desktop:max-w-[240px] bg-white border-r border-[#ececec]',
          isSmallScreen && 'fixed left-0 top-0 z-[60] h-[100dvh]',
        )}
        style={{
          width: navVisible ? navWidth : '0px',
          visibility: navVisible ? 'visible' : 'hidden',
          transition: 'width 0.2s, visibility 0.2s',
        }}
      >
        <div className="h-full w-[240px] touch-mobile:w-full touch-desktop:w-[240px]">
          <div className="flex h-full min-h-0 flex-col">
            <div
              className={cn(
                'flex h-full min-h-0 flex-col transition-opacity',
                'opacity-100',
              )}
            >
              <div
                className={cn(
                  'scrollbar-trigger relative h-full w-full flex-1 items-start border-white/20',
                )}
              >
                <nav
                  id="chat-history-nav"
                  aria-label={localize('com_ui_chat_history')}
                  className="flex h-full min-h-0 w-full flex-col px-3 touch-mobile:p-2"
                >
                  {/* 新建 */}
                  <NewChat
                    toggleNav={toggleNavVisible}
                    isSmallScreen={isSmallScreen}
                    showToggleButton
                  />
                  <div
                    className={cn(
                      '-mr-2 min-h-0 flex-1 flex-col overflow-y-auto scroll-no-hover pr-2 touch-mobile:-mr-0 touch-mobile:pr-0',
                    )}
                    ref={containerRef}
                  >
                    {/* 会话列表 */}
                    <Conversations
                      conversations={conversations}
                      moveToTop={moveToTop}
                      toggleNav={itemToggleNav}
                    />
                    {(isFetchingNextPage || showLoading) && (
                      <Spinner className={cn('m-1 mx-auto mb-4 h-4 w-4 text-text-primary')} />
                    )}
                  </div>
                  {isSmallScreen ? <ChatNavUserFooter /> : null}
                </nav>
              </div>
            </div>
          </div>
        </div>
      </div>
      {!isSmallScreen && (
        <NavToggle
          navVisible={navVisible}
          onToggle={toggleNavVisible}
          isHovering={isHovering}
          setIsHovering={setIsHovering}
          className="fixed top-1/2 z-[50]"
          translateX={236}
        />
      )}
      {isSmallScreen && (
        <div
          id="mobile-nav-mask-toggle"
          role="button"
          tabIndex={0}
          className={`nav-mask ${navVisible ? 'active' : ''}`}
          onClick={toggleNavVisible}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              toggleNavVisible();
            }
          }}
          aria-label="Toggle navigation"
        />
      )}
    </>
  );
};

export default memo(Nav);
