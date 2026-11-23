// @ts-strict-ignore
import React, { useMemo, memo } from 'react';
import type { Assistant, Agent, TMessage } from '~/types/chat';
import type { TMessageIcon } from '~/common';
import { getEndpointField, getIconEndpoint, logger } from '~/utils';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import { useGetEndpointsQuery } from '~/hooks/queries/data-provider';
import Icon from '~/components/Endpoints/Icon';
import { useAuthContext } from '~/hooks/AuthContext';
import { useShareContext } from '~/Providers/ShareContext';
import { resolveChatAuthor } from '~/utils/chatAuthor';

const MessageIcon = memo(
  ({
    iconData,
    message,
    assistant,
    agent,
  }: {
    iconData?: TMessageIcon;
    assistant?: Assistant;
    agent?: Agent;
    message?: Pick<TMessage, 'user_id' | 'user_name'>;
  }) => {
    logger.log('icon_data', iconData, assistant, agent);
    const { data: endpointsConfig } = useGetEndpointsQuery();
    const { user } = useAuthContext();
    const { isSharedConvo } = useShareContext();

    const agentName = useMemo(() => agent?.name ?? '', [agent]);
    const agentAvatar = useMemo(() => agent?.avatar?.filepath ?? '', [agent]);
    const assistantName = useMemo(() => assistant?.name ?? '', [assistant]);
    const assistantAvatar = useMemo(() => assistant?.metadata?.avatar ?? '', [assistant]);

    const avatarURL = useMemo(() => {
      let result = '';
      if (assistant) {
        result = assistantAvatar;
      } else if (agent) {
        result = agentAvatar;
      }
      return result;
    }, [assistant, agent, assistantAvatar, agentAvatar]);

    const iconURL = iconData?.iconURL;
    const endpoint = useMemo(
      () => getIconEndpoint({ endpointsConfig, iconURL, endpoint: iconData?.endpoint }),
      [endpointsConfig, iconURL, iconData?.endpoint],
    );

    const endpointIconURL = useMemo(
      () => getEndpointField(endpointsConfig, endpoint, 'iconURL'),
      [endpointsConfig, endpoint],
    );

    // Model icon
    if (iconData?.isCreatedByUser !== true && iconURL != null ) {
      return (
        <ConvoIconURL
          iconURL={iconURL}
          modelLabel={iconData?.modelLabel}
          context="message"
          assistantAvatar={assistantAvatar}
          agentAvatar={agentAvatar}
          endpointIconURL={endpointIconURL}
          assistantName={assistantName}
          agentName={agentName}
        />
      );
    }

    const author = iconData?.isCreatedByUser
      ? resolveChatAuthor(message ?? {}, isSharedConvo ? undefined : user)
      : undefined;
    return (
      <Icon
        isCreatedByUser={iconData?.isCreatedByUser ?? false}
        endpoint={endpoint}
        name={author?.name}
        userAvatar={author?.avatar}
        iconURL={avatarURL || endpointIconURL}
        model={iconData?.model}
        assistantName={assistantName}
        agentName={agentName}
        size={28.8}
      />
    );
  },
);

MessageIcon.displayName = 'MessageIcon';

export default MessageIcon;
