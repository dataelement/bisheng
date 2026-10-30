import type { MutableRefObject } from 'react';
import { Outlined } from 'bisheng-icons';
import type { Article } from '~/api/channels';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useLocalize, useWorkbenchMenuNames } from '~/hooks';
import FullScreenArticle from './Article/FullScreenArticle';

interface SubscriptionLoadingViewProps {
  mobile: boolean;
  onOpenMobileNav: () => void;
}

export function SubscriptionLoadingView({ mobile, onOpenMobileNav }: SubscriptionLoadingViewProps) {
  const localize = useLocalize();
  const menuNames = useWorkbenchMenuNames();
  return (
    <div className="relative flex flex-1 flex-col items-center justify-center py-10 text-center text-text-3">
      {mobile && (
        <div className="absolute inset-x-0 top-0 z-10 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
          <div className="relative flex h-11 items-center px-4">
            <button type="button" aria-label={localize('com_nav_open_sidebar')} onClick={onOpenMobileNav}
              className="workbench-menu-trigger relative inline-flex size-5 items-center justify-center text-text-1">
              <Outlined.SidebarMenu className="size-5" />
            </button>
            <h1 className="pointer-events-none absolute left-1/2 max-w-[calc(100%-112px)] -translate-x-1/2 truncate text-h4 font-medium text-text-1">{menuNames.channel}</h1>
          </div>
        </div>
      )}
      <LoadingIcon className="size-20 text-primary" />
    </div>
  );
}

interface SubscriptionArticleOverlayProps {
  article: Article;
  mobile: boolean;
  showAiAssistant: boolean;
  showFullScreenBtn: boolean;
  enteredViaAiRef: MutableRefObject<boolean>;
  onClose: () => void;
  onAiAssistantChange: (open: boolean) => void;
  onShowFullScreenBtnChange: (show: boolean) => void;
}

export function SubscriptionArticleOverlay({
  article, mobile, showAiAssistant, showFullScreenBtn, enteredViaAiRef,
  onClose, onAiAssistantChange, onShowFullScreenBtnChange,
}: SubscriptionArticleOverlayProps) {
  const closeOverlay = () => {
    onClose();
    onAiAssistantChange(false);
    enteredViaAiRef.current = false;
  };
  return (
    <div className="absolute inset-0 z-50 flex h-full flex-col bg-white">
      <FullScreenArticle
        article={article}
        showAiAssistant={showAiAssistant}
        showFullScreenBtn={showFullScreenBtn}
        setShowAiAssistant={onAiAssistantChange}
        onExit={closeOverlay}
        onSwitchToFullScreen={() => {
          onAiAssistantChange(false);
          onShowFullScreenBtnChange(false);
          enteredViaAiRef.current = false;
        }}
        onCloseAiAssistant={() => {
          if (enteredViaAiRef.current && !mobile) closeOverlay();
          else onAiAssistantChange(false);
        }}
      />
    </div>
  );
}
