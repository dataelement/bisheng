import { useMemo } from 'react';
import { UserAvatar } from '@bisheng/ui';
import type { TMessage, TPreset, Assistant, Agent } from '~/types/chat';
import type { TMessageProps } from '~/common';
import MessageEndpointIcon from '../Endpoints/MessageEndpointIcon';
import ConvoIconURL from '~/components/Endpoints/ConvoIconURL';
import { getIconEndpoint } from '~/utils';
import { resolveChatAuthor } from '~/utils/chatAuthor';

export default function MessageIcon(
  props: Pick<TMessageProps, 'message' | 'conversation'> & {
    assistant?: false | Assistant;
    agent?: false | Agent;
  },
) {
  const { message, conversation, assistant, agent } = props;

  const assistantName = assistant ? (assistant.name as string | undefined) : '';
  const assistantAvatar = assistant ? (assistant.metadata?.avatar as string | undefined) : '';
  const agentName = agent ? (agent.name as string | undefined) : '';
  const agentAvatar = agent ? (agent.metadata?.avatar as string | undefined) : '';

  const messageSettings = useMemo(
    () => ({
      ...(conversation ?? {}),
      ...({
        ...message,
        iconURL: message?.iconURL ?? '',
      } as TMessage),
    }),
    [conversation, message],
  );

  const iconURL = messageSettings.iconURL ?? '';
  let endpoint = messageSettings.endpoint;
  endpoint = getIconEndpoint({ endpointsConfig: undefined, iconURL, endpoint });

  if (message?.isCreatedByUser !== true && iconURL && iconURL.includes('http')) {
    return (
      <ConvoIconURL
        iconURL={iconURL}
        modelLabel={messageSettings.chatGptLabel ?? messageSettings.modelLabel ?? ''}
        context="message"
        assistantAvatar={assistantAvatar}
        assistantName={assistantName}
        agentAvatar={agentAvatar}
        agentName={agentName}
      />
    );
  }

  if (message?.isCreatedByUser === true) {
    const author = resolveChatAuthor(message);
    return <UserAvatar className="size-5" fallbackClassName="text-caption-sm" name={author.name} src={author.avatar} />;
  }

  return (
    <MessageEndpointIcon
      {...messageSettings}
      endpoint={endpoint}
      iconURL={assistant == null ? undefined : assistantAvatar}
      model={message?.model ?? conversation?.model}
      assistantName={assistantName}
      agentName={agentName}
      size={28.8}
    />
  );
}
