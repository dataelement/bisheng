import { useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { icons } from '~/components/Chat/Menus/Endpoints/Icons';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import { useGetBsConfig, useGetEndpointsQuery } from '~/data-provider';
import type { TConversation, TMessage } from '~/data-provider/data-provider/src';
import { Constants, QueryKeys } from '~/data-provider/data-provider/src';
import { useLocalize, useNewConvo } from '~/hooks';
import store from '~/store';
import { getEndpointField, getIconEndpoint, getIconKey } from '~/utils';

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
}: {
  index?: number;
  toggleNav: () => void;
  subHeaders?: React.ReactNode;
  isSmallScreen: boolean;
}) {
  const queryClient = useQueryClient();
  /** Note: this component needs an explicit index passed if using more than one */
  const { newConversation: newConvo } = useNewConvo(index);
  const { data: bsConfig } = useGetBsConfig()

  const navigate = useNavigate();
  const localize = useLocalize();

  const { conversation } = store.useCreateConversationAtom(index);

  const clickHandler = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.button === 0 && !(event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      queryClient.setQueryData<TMessage[]>(
        [QueryKeys.messages, conversation?.conversationId ?? Constants.NEW_CONVO],
        [],
      );
      newConvo();
      navigate('/c/new');
      toggleNav();
    }
  };

  return (
    <div className="sticky left-0 right-0 top-0 z-50 bg-[#F9FBFF]">
      <div className="pb-0.5 last:pb-0" style={{ transform: 'none' }}>
        <div className="mb-3 flex justify-between gap-3 px-3 py-2">
          <div className="flex items-center gap-2">
            {bsConfig?.sidebarIcon.image && <img className='w-10 overflow' src={__APP_ENV__.BASE_URL + bsConfig?.sidebarIcon.image} />}
            <div className='dark:text-gray-50'>{bsConfig?.sidebarSlogan}</div>
          </div>
          <div className="cursor-pointer rounded-md p-1 hover:bg-slate-100">
            {/* <CloseToggleIcon className="size-5" /> */}
          </div>
        </div>
        {/* 新建btn */}
        <button
          className="flex items-center w-full shadow-sm bg-white mx-auto border px-4 py-3 rounded-xl "
          onClick={clickHandler}
          aria-label={localize('com_ui_new_chat')}
        >
          <img className='size-[18px] grayscale' src={__APP_ENV__.BASE_URL + '/assets/chat2.png'} alt="" />
          <span className="text-sm pl-2.5">{localize('com_ui_new_chat')}</span>
        </button>
      </div>
      {subHeaders != null ? subHeaders : null}
    </div>
  );
}
