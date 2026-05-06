import type { ConversationListResponse } from '~/types/chat';
import { PermissionTypes, Permissions } from '~/types/chat';
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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

  const [navWidth, setNavWidth] = useState('240px');
  const [isHovering, setIsHovering] = useState(false);
  const navPanelRef = useRef<HTMLDivElement>(null);
  const [navPanelRightPx, setNavPanelRightPx] = useState(0);
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
      // 移动端：与知识/订阅/应用中心侧栏统一 240px
      setNavWidth('240px');
    } else {
      setNavWidth('240px');
    }
  }, [isSmallScreen]);

  // 折叠把手贴在会话列表右缘（分隔线右侧），需计入 MainLayout 窄轨 + main 内边距，故用测量值而非假定 left:0 + translateX
  useLayoutEffect(() => {
    if (isSmallScreen) {
      return;
    }
    const el = navPanelRef.current;
    if (!el) {
      return;
    }
    const sync = () => {
      setNavPanelRightPx(el.getBoundingClientRect().right);
    };
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    window.addEventListener('resize', sync);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', sync);
    };
  }, [isSmallScreen, navVisible, navWidth]);

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
        ref={navPanelRef}
        data-testid="nav"
        className={cn(
          // 须与 usePrefersMobileLayout（max-width:767px）一致：touch-mobile 为 max-1023，误伤 768–1023 会去掉边距/边框，像「盖在内容上」
          'max-w-[260px] max-[767px]:max-w-none min-w-0 flex-shrink-0 overflow-x-hidden bg-white border-r border-[#ececec] max-[767px]:border-r-0',
          isSmallScreen && 'fixed inset-y-0 left-0 z-[70] h-[100dvh] shadow-[4px_0_24px_rgba(0,0,0,0.06)]',
        )}
        style={{
          width: navVisible ? navWidth : '0px',
          visibility: navVisible ? 'visible' : 'hidden',
          transition: 'width 0.2s, visibility 0.2s',
        }}
      >
        <div className="h-full w-[240px] max-[767px]:w-full">
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
                  className="flex h-full min-h-0 w-full flex-col gap-4 py-5 px-3 max-[767px]:gap-0 max-[767px]:p-0"
                >
                  {/* 新建 */}
                  <NewChat
                    toggleNav={toggleNavVisible}
                    isSmallScreen={isSmallScreen}
                    showToggleButton
                  />
                  <div
                    className={cn(
                      '-mr-2 min-h-0 flex-1 flex-col overflow-y-auto scroll-no-hover pr-2 max-[767px]:-mr-0 max-[767px]:pr-0',
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
      {!isSmallScreen && navPanelRightPx > 0 ? (
        <NavToggle
          navVisible={navVisible}
          onToggle={toggleNavVisible}
          isHovering={isHovering}
          setIsHovering={setIsHovering}
          className=""
          anchorRightEdgePx={navPanelRightPx}
        />
      ) : null}
      {isSmallScreen && (
        <div
          id="mobile-nav-mask-toggle"
          role="button"
          tabIndex={0}
          className={cn(
            'fixed inset-0 z-[69] min-w-0 bg-[rgba(86,88,105,0.55)] transition-opacity',
            navVisible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none',
          )}
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
