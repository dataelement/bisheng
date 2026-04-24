import { useQueryClient } from '@tanstack/react-query';
import { Plus, Search, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { icons } from '~/components/Chat/Menus/Endpoints/Icons';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import { useGetBsConfig, useGetEndpointsQuery } from '~/hooks/queries/data-provider';
import type { TConversation, TMessage } from '~/types/chat';
import { Constants, QueryKeys } from '~/types/chat';
import { useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { getEndpointField, getIconEndpoint, getIconKey } from '~/utils';
import { HubModuleNavTabs } from '~/components/Nav/HubModuleNavTabs';
import { Button } from '../ui';

const NewChatButtonIcon = ({ conversation }: { conversation: TConversation | null }) => {
  const searchQuery = useRecoilValue(store.searchQuery);
  const { data: endpointsConfig } = useGetEndpointsQuery();

  if (searchQuery) {
    return (
      <div className="shadow-stroke relative flex h-7 w-7 items-center justify-center rounded-full bg-white text-black dark:bg-white">
        <Search className="h-5 w-5" />
      </div>
    );
  }

  let { endpoint = '' } = conversation ?? {};
  const iconURL = conversation?.iconURL ?? '';
  endpoint = getIconEndpoint({ endpointsConfig, iconURL, endpoint });

  const endpointType = getEndpointField(endpointsConfig, endpoint, 'type');
  const endpointIconURL = getEndpointField(endpointsConfig, endpoint, 'iconURL');
  const iconKey = getIconKey({ endpoint, endpointsConfig, endpointType, endpointIconURL });
  const Icon = icons[iconKey];

  return (
    <div className="h-7 w-7 flex-shrink-0">
      {iconURL && iconURL.includes('http') ? (
        <ConvoIconURL
          iconURL={iconURL}
          modelLabel={conversation?.chatGptLabel ?? conversation?.modelLabel ?? ''}
          endpointIconURL={iconURL}
          context="nav"
        />
      ) : (
        <div className="shadow-stroke relative flex h-full items-center justify-center rounded-full bg-white text-black">
          {endpoint && Icon != null && (
            <Icon
              size={41}
              context="nav"
              className="h-2/3 w-2/3"
              endpoint={endpoint}
              endpointType={endpointType}
              iconURL={endpointIconURL}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default function NewChat({
  index = 0,
  toggleNav,
  subHeaders,
  isSmallScreen,
  showToggleButton = true,
}: {
  index?: number;
  toggleNav: () => void;
  subHeaders?: React.ReactNode;
  isSmallScreen: boolean;
  showToggleButton?: boolean;
}) {
  const queryClient = useQueryClient();
  /** Note: this component needs an explicit index passed if using more than one */
  const { newConversation: newConvo } = useNewConvo(index);
  const { data: bsConfig } = useGetBsConfig()
  const navigate = useNavigate();
  const localize = useLocalize();

  const { conversation } = store.useCreateConversationAtom(index);

  const clickHandler = (event: React.MouseEvent<HTMLElement>) => {
    if (event.button === 0 && !(event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      newConvo();
      navigate('/c/new');
      // Keep auto-collapse behavior only on small screens.
      if (isSmallScreen) {
        toggleNav();
      }
      queryClient.setQueryData<TMessage[]>(
        [QueryKeys.messages, conversation?.conversationId ?? Constants.NEW_CONVO],
        [],
      );
    }
  };

  return (
    <div className="sticky left-0 right-0 top-0 z-50 bg-white">
      <div className="" style={{ transform: 'none' }}>
        {isSmallScreen ? (
          <div className="shrink-0 py-2.5">
            <div className="flex items-center justify-between">
              {bsConfig?.sidebarIcon?.image ? (
                <img
                  className="h-8 w-8 rounded-md object-contain"
                  src={bsConfig.sidebarIcon.image}
                  alt={localize('com_nav_home')}
                />
              ) : (
                <div className="h-8 w-8 rounded-md bg-[#F2F3F5]" aria-hidden />
              )}
              <button
                type="button"
                onClick={toggleNav}
                aria-label={localize('com_nav_close_sidebar')}
                className="inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] hover:bg-[#F7F8FA]"
              >
                <X className="size-4" strokeWidth={2} />
              </button>
            </div>
          </div>
        ) : (
          <div className="py-5">
            <div className="border-b border-[#e5e6eb] pb-4">
              <div className="flex items-center text-[16px] font-medium">
                <span className="leading-6 text-[#212121]">{localize('com_nav_home')}</span>
              </div>
              <div className="mt-4 flex w-full gap-1">
                {/* 新建btn */}
                <Button
                  variant="outline"
                  className="w-full flex items-center justify-center gap-[8px] border border-[#e3e3e3] rounded-[6px] px-[12px] py-[5px] h-auto shadow-none text-[#212121] font-normal"
                  aria-label={localize('com_ui_new_chat')}
                  onClick={() => {
                    document.getElementById("create-convo-btn")?.click();
                    // hack
                    setTimeout(() => {
                      document.getElementById("create-convo-btn")?.click();
                    }, 300);
                  }}
                >
                  <Plus className='size-[20px] text-[#212121]' />
                  <span className="text-[14px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_chat')}</span>
                </Button>
              </div>
            </div>
          </div>
        )}
        {/* 与 SideNavModuleTabs 一致：仅小屏（<=768）展示四等分模块入口 */}
        {isSmallScreen && (
          <div className="mb-2 w-full min-w-0 shrink-0">
            <HubModuleNavTabs equalWidth className="w-full min-w-0" />
          </div>
        )}
        {isSmallScreen && (
          <div className='flex gap-1 w-full'>
            {/* 新建btn */}
            <Button
              variant="outline"
              className="w-full flex items-center justify-center gap-[8px] border border-[#e3e3e3] rounded-[6px] px-[12px] py-[5px] h-auto shadow-none text-[#212121] font-normal"
              aria-label={localize('com_ui_new_chat')}
              onClick={() => {
                document.getElementById("create-convo-btn")?.click();
                // hack
                setTimeout(() => {
                  document.getElementById("create-convo-btn")?.click();
                }, 300);
              }}
            >
              <Plus className='size-[20px] text-[#212121]' />
              <span className="text-[14px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_chat')}</span>
            </Button>
          </div>
        )}
      </div>
      <div id="create-convo-btn" className='opacity-0' onClick={clickHandler}></div>
      {subHeaders != null ? subHeaders : null}
    </div>
  );
}