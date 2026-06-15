import { useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { icons } from '~/components/Chat/Menus/Endpoints/Icons';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import { useGetBsConfig, useGetEndpointsQuery } from '~/hooks/queries/data-provider';
import type { TConversation, TMessage } from '~/types/chat';
import { Constants, QueryKeys } from '~/types/chat';
import { useAuthContext, useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { cn, getEndpointField, getIconEndpoint, getIconKey } from '~/utils';
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
  const { user } = useAuthContext();

  const { conversation } = store.useCreateConversationAtom(index);

  // F035 Track H (P5): "new task" sidebar entry — only for users holding the
  // linsight_task_mode menu permission (backend web_menu mapped to plugins;
  // absent plugins array = legacy mode, everything allowed) and when the
  // admin hasn't disabled the linsight entry.
  const plugins: string[] | null = Array.isArray((user as any)?.plugins)
    ? ((user as any)?.plugins as string[])
    : null;
  const showNewTaskEntry =
    (plugins ? plugins.includes('linsight_task_mode') : true) &&
    ((bsConfig as any)?.linsightConfig?.linsight_entry ?? true);

  const handleNewTask = () => {
    navigate('/linsight/new');
    if (isSmallScreen) {
      toggleNav();
    }
  };

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
    <div
      className={cn(
        'sticky left-0 right-0 top-0 bg-white',
        isSmallScreen ? 'z-50' : 'z-10',
      )}
    >
      <div className="" style={{ transform: 'none' }}>
        {isSmallScreen ? (
          <MobileSidebarHeaderTabs
            logoSrc={bsConfig?.sidebarIcon?.image ? __APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image : undefined}
            onClose={toggleNav}
            onLinkClick={(link) => {
              if (link.closeDrawerOnNavigate) {
                toggleNav();
              }
            }}
          />
        ) : (
          <div>
            <div className="pb-0">
              <div className="flex items-center pl-3">
                <span className="text-base font-bold leading-8 text-[#1A1A1A]">{localize('com_nav_home')}</span>
              </div>
              <div className="mt-5 flex w-full flex-col gap-1">
                {/* Create chat button */}
                <Button
                  variant="outline"
                  className="w-full flex items-center justify-start gap-[8px] border-none rounded-lg px-2 py-1.5 h-auto shadow-none text-[#1A1A1A] font-normal hover:bg-[#F5F5F5] transition-colors"
                  aria-label={localize('com_ui_new_chat')}
                  onClick={() => {
                    document.getElementById("create-convo-btn")?.click();
                    // hack
                    setTimeout(() => {
                      document.getElementById("create-convo-btn")?.click();
                    }, 300);
                  }}
                >
                  <Outlined.MessagePlus size={16} className='text-[#1A1A1A]' />
                  <span className="text-[14px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_chat')}</span>
                </Button>
                {showNewTaskEntry && (
                  /* Create task button */
                  <Button
                    variant="outline"
                    className="w-full flex items-center justify-start gap-[8px] border-none rounded-lg px-2 py-1.5 h-auto shadow-none text-[#1A1A1A] font-normal hover:bg-[#F5F5F5] transition-colors"
                    aria-label={localize('com_nav_start_new_task')}
                    onClick={handleNewTask}
                  >
                    <Outlined.Binoculars size={16} className='text-[#1A1A1A]' />
                    <span className="text-[14px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_task')}</span>
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
        {isSmallScreen && (
          <div className='flex w-full flex-col gap-2 px-3 pb-6 pt-4'>
            {/* Create chat button for mobile */}
            <Button
              variant="outline"
              className="flex h-9 w-full items-center justify-center gap-2 border border-[#EBECF0] bg-white rounded-lg text-[13px] text-[#1A1A1A] hover:bg-[#F5F5F5]"
              aria-label={localize('com_ui_new_chat')}
              onClick={() => {
                document.getElementById("create-convo-btn")?.click();
                // hack
                setTimeout(() => {
                  document.getElementById("create-convo-btn")?.click();
                }, 300);
              }}
            >
              <Outlined.MessagePlus size={16} className='text-[#1A1A1A]' />
              <span className="text-[13px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_chat')}</span>
            </Button>
            {showNewTaskEntry && (
              /* Create task button for mobile */
              <Button
                variant="outline"
                className="flex h-9 w-full items-center justify-center gap-2 border border-[#EBECF0] bg-white rounded-lg text-[13px] text-[#1A1A1A] hover:bg-[#F5F5F5]"
                aria-label={localize('com_nav_start_new_task')}
                onClick={handleNewTask}
              >
                <Outlined.Binoculars size={16} className='text-[#1A1A1A]' />
                <span className="text-[13px] leading-[20px] whitespace-nowrap">{localize('com_nav_start_new_task')}</span>
              </Button>
            )}
          </div>
        )}
      </div>
      <div id="create-convo-btn" className='opacity-0' onClick={clickHandler}></div>
      {subHeaders != null ? subHeaders : null}
    </div>
  );
}
