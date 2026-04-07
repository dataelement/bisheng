import { useQueryClient } from '@tanstack/react-query';
import { Search, PanelRightOpen, Plus, X } from 'lucide-react';
import { matchPath, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { icons } from '~/components/Chat/Menus/Endpoints/Icons';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import { useGetBsConfig, useGetEndpointsQuery } from '~/hooks/queries/data-provider';
import type { TConversation, TMessage } from '~/types/chat';
import { Constants, QueryKeys } from '~/types/chat';
import { useAuthContext, useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { getEndpointField, getIconEndpoint, getIconKey } from '~/utils';
import { cn } from '~/utils';
import { Button } from '../ui';
import BookOpenIcon from '../ui/icon/BookOpen';
import GlobeIcon from '../ui/icon/Globe';
import HomeIcon from '../ui/icon/Home';
import LinkIcon from '../ui/icon/Link';

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
  const { pathname } = useLocation();
  const { user } = useAuthContext();
  /** Note: this component needs an explicit index passed if using more than one */
  const { newConversation: newConvo } = useNewConvo(index);
  const { data: bsConfig } = useGetBsConfig()

  const navigate = useNavigate();
  const localize = useLocalize();

  const plugins: string[] | null = Array.isArray((user as any)?.plugins)
    ? ((user as any)?.plugins as string[])
    : null;
  const showSubscriptionTab = plugins ? plugins.includes('subscription') : true;
  const showKnowledgeSpaceTab = plugins ? plugins.includes('knowledge_space') : true;

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

  const drawerQuickLinks = [
    {
      to: '/c/new',
      icon: HomeIcon,
      active: /^\/(c|linsight)(\/|$)/.test(pathname),
    },
    {
      to: '/apps',
      icon: GlobeIcon,
      active: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
    },
    ...(showSubscriptionTab
      ? [{ to: '/channel', icon: LinkIcon, active: pathname.startsWith('/channel') }]
      : []),
    ...(showKnowledgeSpaceTab
      ? [{ to: '/knowledge', icon: BookOpenIcon, active: pathname.startsWith('/knowledge') }]
      : []),
  ] as const;

  return (
    <div className="sticky left-0 right-0 top-0 z-50 bg-white max-[575px]:bg-white">
      <div className="" style={{ transform: 'none' }}>
        {isSmallScreen ? (
          <div className="mb-4 max-[575px]:mb-4">
            <div className="flex items-center justify-between gap-2 max-[575px]:mb-3">
              {bsConfig?.assistantIcon?.image ? (
                <img
                  src={__APP_ENV__.BASE_URL + bsConfig.assistantIcon.image}
                  alt=""
                  className="size-9 shrink-0 object-contain rounded-lg"
                />
              ) : (
                <span className="font-medium text-[#212121] text-[14px]">{localize('com_ui_new_chat')}</span>
              )}
              {showToggleButton ? (
                <button
                  type="button"
                  onClick={toggleNav}
                  className="rounded-lg p-2 hover:bg-slate-100 text-[#212121]"
                  aria-label={localize('com_nav_close_sidebar')}
                >
                  <X className="size-5" />
                </button>
              ) : null}
            </div>
            <div className="flex items-stretch justify-between gap-1 max-[575px]:mb-3 max-[575px]:px-0.5">
              {drawerQuickLinks.map(({ to, icon: Icon, active }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={cn(
                    'flex flex-1 items-center justify-center rounded-lg py-2 transition-colors',
                    active ? 'bg-[#e6edfc]' : 'hover:bg-[#f7f8fa]',
                  )}
                  onClick={() => toggleNav()}
                >
                  <Icon className={cn('size-5', active ? 'text-[#335CFF]' : 'text-[#818181]')} />
                </NavLink>
              ))}
            </div>
          </div>
        ) : (
          <div className="mb-4 flex items-center justify-between">
            <p className="font-medium text-[#212121] text-[14px]">首页</p>
            {showToggleButton ? (
              <div className="cursor-pointer rounded-md p-1 hover:bg-slate-100" onClick={toggleNav}>
                <PanelRightOpen className="size-4 text-[#86909c]" />
              </div>
            ) : null}
          </div>
        )}
        <div className='flex gap-1 w-full'>
          {/* 新建btn */}
          <Button
            variant="outline"
            className="w-full flex items-center justify-center gap-[8px] border border-[#e3e3e3] max-[575px]:border-[#ececec] rounded-[8px] max-[575px]:rounded-[8px] px-[12px] py-[8px] max-[575px]:py-2.5 h-auto shadow-none text-[#212121] font-normal bg-white max-[575px]:bg-white"
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
      <div id="create-convo-btn" className='opacity-0' onClick={clickHandler}></div>
      {subHeaders != null ? subHeaders : null}
    </div>
  );
}
