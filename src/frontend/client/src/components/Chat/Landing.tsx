import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { useAgentsMapContext, useAssistantsMapContext, useChatContext } from '~/Providers';
import {
  useGetAssistantDocsQuery,
  useGetBsConfig,
  useGetEndpointsQuery,
  useGetStartupConfig,
} from '~/data-provider';
import type * as t from '~/data-provider/data-provider/src';
import { Constants, EModelEndpoint } from '~/data-provider/data-provider/src';
import { useLocalize, useSubmitMessage } from '~/hooks';
import { cn, getEntity, getIconEndpoint } from '~/utils';
import ConvoStarter from './ConvoStarter';
import SegmentSelector from './SegmentSelector';

export default function Landing({ Header, isNew, lingsi, setLingsi }: { Header?: ReactNode; isNew?: boolean, lingsi: boolean }) {
  const { conversation } = useChatContext();
  const agentsMap = useAgentsMapContext();
  const assistantMap = useAssistantsMapContext();
  const { data: startupConfig } = useGetStartupConfig();
  const { data: endpointsConfig } = useGetEndpointsQuery();
  const { data: bsConfig } = useGetBsConfig()

  const localize = useLocalize();

  let { endpoint = '' } = conversation ?? {};

  if (
    endpoint === EModelEndpoint.chatGPTBrowser ||
    endpoint === EModelEndpoint.azureOpenAI ||
    endpoint === EModelEndpoint.gptPlugins
  ) {
    endpoint = EModelEndpoint.openAI;
  }

  const iconURL = conversation?.iconURL;
  endpoint = getIconEndpoint({ endpointsConfig, iconURL, endpoint });
  const { data: documentsMap = new Map() } = useGetAssistantDocsQuery(endpoint, {
    select: (data) => new Map(data.map((dbA) => [dbA.assistant_id, dbA])),
  });

  const { entity, isAgent, isAssistant } = getEntity({
    endpoint,
    agentsMap,
    assistantMap,
    agent_id: conversation?.agent_id,
    assistant_id: conversation?.assistant_id,
  });

  const name = entity?.name ?? '';
  const description = entity?.description ?? '';
  const avatar = isAgent
    ? ((entity as t.Agent | undefined)?.avatar?.filepath ?? '')
    : (((entity as t.Assistant | undefined)?.metadata?.avatar as string | undefined) ?? '');
  const conversation_starters = useMemo(() => {
    /* The user made updates, use client-side cache, or they exist in an Agent */
    if (entity && (entity.conversation_starters?.length ?? 0) > 0) {
      return entity.conversation_starters;
    }
    if (isAgent) {
      return entity?.conversation_starters ?? [];
    }

    /* If none in cache, we use the latest assistant docs */
    const entityDocs = documentsMap.get(entity?.id ?? '');
    return entityDocs?.conversation_starters ?? [];
  }, [documentsMap, isAgent, entity]);

  const containerClassName =
    'shadow-stroke relative flex h-full items-center justify-center rounded-full bg-white text-black';

  const { submitMessage } = useSubmitMessage();
  const sendConversationStarter = (text: string) => submitMessage({ text });

  const getWelcomeMessage = () => {
    const greeting = conversation?.greeting ?? '';
    if (greeting) {
      return greeting;
    }

    if (isAssistant) {
      return localize('com_nav_welcome_assistant');
    }

    if (isAgent) {
      return localize('com_nav_welcome_agent');
    }

    return typeof startupConfig?.interface?.customWelcome === 'string'
      ? startupConfig?.interface?.customWelcome
      : localize('com_nav_welcome_message');
  };


  return (
    <div className={cn('relative', !isNew && 'h-full')}>
      <div className="absolute left-0 right-0">{Header != null ? Header : null}</div>
      <div className="flex h-full flex-col items-center justify-center">
        <div className='flex items-center gap-4'>
          {bsConfig?.assistantIcon.image && <img className="overflow w-[52px]" src={__APP_ENV__.BASE_URL + bsConfig?.assistantIcon.image} />}
          <h2 className="max-w-[75vh] px-12 text-center text-lg font-medium dark:text-white md:px-0 md:text-2xl">
            {bsConfig?.welcomeMessage}
          </h2>
        </div>
        <div className="max-w-lg text-center mt-4 text-sm font-normal text-gray-500">
          {bsConfig?.functionDescription}
        </div>

        {/* 引导词 */}
        <div className="mt-8 flex flex-wrap justify-center gap-3 px-4">
          {conversation_starters.length > 0 &&
            conversation_starters
              .slice(0, Constants.MAX_CONVO_STARTERS)
              .map((text: string, index: number) => (
                <ConvoStarter
                  key={index}
                  text={text}
                  onClick={() => sendConversationStarter(text)}
                />
              ))}
        </div>

        {/* 模式切换 */}
        <div className='mx-auto mb-6 mt-2'>
          <SegmentSelector lingsi={lingsi} onChange={setLingsi} />
        </div>
      </div>
    </div>
  );
}
