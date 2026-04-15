import { useQueryClient } from '@tanstack/react-query';
import { Search, Plus } from 'lucide-react';
import { matchPath, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { icons } from '~/components/Chat/Menus/Endpoints/Icons';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import BookOpenIcon from '~/components/ui/icon/BookOpen';
import GlobeIcon from '~/components/ui/icon/Globe';
import HomeIcon from '~/components/ui/icon/Home';
import LinkIcon from '~/components/ui/icon/Link';
import { useGetBsConfig, useGetEndpointsQuery } from '~/hooks/queries/data-provider';
import type { TConversation, TMessage } from '~/types/chat';
import { Constants, QueryKeys } from '~/types/chat';
import { useAuthContext, useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { cn, getEndpointField, getIconEndpoint, getIconKey } from '~/utils';
import { appsSectionLinkTarget, lastSectionPaths } from '~/layouts/appModuleNavPaths';
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
  const { pathname } = useLocation();
  const { user } = useAuthContext();

  const navigate = useNavigate();
  const localize = useLocalize();
  const plugins: string[] | null = Array.isArray((user as { plugins?: string[] })?.plugins)
    ? (user as { plugins: string[] }).plugins
    : null;
  const showSubscriptionTab = plugins ? plugins.includes('subscription') : true;
  const showKnowledgeSpaceTab = plugins ? plugins.includes('knowledge_space') : true;

  const { conversation } = store.useCreateConversationAtom(index);

  const clickHandler = (event: React.MouseEvent<HTMLAnchorElement>) => {
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
        <div className="mb-4 flex items-center justify-between">
          <p className="font-medium text-[#212121] text-[16px] ml-2">{localize('com_nav_home')}</p>
        </div>
        <div className="mb-2 flex w-full flex-nowrap items-stretch gap-1 overflow-x-auto pb-1 md:hidden scrollbar-hide">
          {[
            {
              section: 'home',
              to: lastSectionPaths.home || '/c/new',
              icon: HomeIcon,
              label: localize('com_nav_home'),
              isActive: /^\/(c|linsight)(\/|$)/.test(pathname),
            },
            {
              section: 'apps',
              to: appsSectionLinkTarget(),
              icon: GlobeIcon,
              label: localize('com_nav_app_center'),
              isActive: matchPath('/app/:id/:fid/:type', pathname) !== null || pathname.startsWith('/apps'),
            },
            {
              section: 'channel',
              to: lastSectionPaths.channel || '/channel',
              icon: LinkIcon,
              label: localize('com_ui_channel'),
              isActive: pathname.startsWith('/channel'),
            },
            {
              section: 'knowledge',
              to: lastSectionPaths.knowledge || '/knowledge',
              icon: BookOpenIcon,
              label: localize('com_knowledge.knowledge_space'),
              isActive: pathname.startsWith('/knowledge'),
            },
          ]
            .filter((l) => {
              if (l.section === 'channel') return showSubscriptionTab;
              if (l.section === 'knowledge') return showKnowledgeSpaceTab;
              return true;
            })
            .map((link) => (
              <NavLink
                key={link.section}
                to={link.to}
                aria-label={link.label}
                className={({ isActive: navActive }) =>
                  cn(
                    'flex min-w-[36px] shrink-0 items-center justify-center rounded-md px-2 py-1.5 transition-colors',
                    navActive || link.isActive
                      ? 'bg-[#e6edfc] font-medium text-[#335CFF]'
                      : 'text-[#4e5969] hover:bg-[#f7f8fa]',
                  )
                }
              >
                {({ isActive: navActive }) => {
                  const on = navActive || link.isActive;
                  const Icon = link.icon;
                  return (
                    <Icon
                      className={cn('size-[14px] shrink-0', on ? 'text-[#335CFF]' : 'text-[#818181]')}
                    />
                  );
                }}
              </NavLink>
            ))}
        </div>
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
      </div>
      <div id="create-convo-btn" className='opacity-0' onClick={clickHandler}></div>
      {subHeaders != null ? subHeaders : null}
    </div>
  );
}