import { useQueryClient } from '@tanstack/react-query';
import { Plus, Search } from 'lucide-react';
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
import { MobileSidebarHeaderTabs } from '~/components/Nav/MobileSidebarHeaderTabs';
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
          <MobileSidebarHeaderTabs
            logoSrc={bsConfig?.sidebarIcon?.image}
            onClose={toggleNav}
            onLinkClick={(link) => {
              if (link.closeDrawerOnNavigate) {
                toggleNav();
              }
            }}
          />
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
        {isSmallScreen && (
          <div className='flex w-full gap-1 px-3 pb-6 pt-4'>
            {/* 新建btn */}
            <Button
              variant="outline"
              className="flex h-9 w-full items-center justify-center gap-1 border border-[#EBECF0] bg-white text-[13px] text-[#212121] hover:bg-[#F7F8FA]"
              aria-label={localize('com_ui_new_chat')}
              onClick={() => {
                document.getElementById("create-convo-btn")?.click();
                // hack
                setTimeout(() => {
                  document.getElementById("create-convo-btn")?.click();
                }, 300);
              }}
            >
              <Plus className='size-4 text-[#212121]' />
              <span className="text-[13px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_chat')}</span>
            </Button>
          </div>
        )}
      </div>
      <div id="create-convo-btn" className='opacity-0' onClick={clickHandler}></div>
      {subHeaders != null ? subHeaders : null}
    </div>
  );
}