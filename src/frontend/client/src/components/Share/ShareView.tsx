import { memo, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import AiChatMessages from '~/components/Chat/AiChatMessages';
import { useCitationReferencePanel } from '~/components/Chat/Messages/Content/useCitationReferencePanel';
import { useGetSharedMessages } from '~/hooks/queries';
import { useLocalize, useDocumentTitle } from '~/hooks';
import { useGetStartupConfig } from '~/hooks/queries/data-provider';
import { ShareContext } from '~/Providers';
import { Spinner } from '~/components/svg';
import Footer from '../Chat/Footer';
import { toSharedChatMessages } from './shareMessageAdapters';

function SharedView() {
  const localize = useLocalize();
  const { data: config } = useGetStartupConfig();
  const { shareId } = useParams();
  const { data, isLoading } = useGetSharedMessages(shareId ?? '');
  const messages = useMemo(() => toSharedChatMessages(data?.messages ?? []), [data?.messages]);
  const hasMessages = messages.length > 0;
  const { activeCitationMessageId, citationPanelElement, onOpenCitationPanel } = useCitationReferencePanel({ hasMessages });

  // configure document title
  let docTitle = '';
  if (config?.appTitle != null && data?.title != null) {
    docTitle = `${data.title} | ${config.appTitle}`;
  } else {
    docTitle = data?.title ?? config?.appTitle ?? document.title;
  }

  useDocumentTitle(docTitle);

  let content: JSX.Element;
  if (isLoading) {
    content = (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="" />
      </div>
    );
  } else if (data && hasMessages) {
    content = (
      <>
        <div className="final-completion group mx-auto flex w-full max-w-[800px] flex-col gap-3 px-4 pb-6 pt-4 sm:px-0 touch-mobile:max-w-full touch-mobile:px-3">
          <h1 className="text-4xl font-bold">{data.title}</h1>
          <div className="border-b border-border-medium pb-6 text-base text-text-secondary">
            {new Date(data.createdAt).toLocaleDateString('en-US', {
              month: 'long',
              day: 'numeric',
              year: 'numeric',
            })}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="relative flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden">
            <AiChatMessages
              messages={messages}
              conversationId={data.conversationId}
              title={data.title}
              isLoading={false}
              isStreaming={false}
              hideHeaderTitle
              hideShare
              knowledgeChatLayout
              contentWidthClassName="w-full max-w-[800px] mx-auto px-4 sm:px-0 touch-mobile:max-w-full touch-mobile:px-3"
              onOpenCitationPanel={onOpenCitationPanel}
              activeCitationMessageId={activeCitationMessageId}
              flatMode
            />
          </div>

          {citationPanelElement}
        </div>
      </>
    );
  } else {
    content = (
      <div className="flex h-screen items-center justify-center ">
        {localize('com_ui_shared_link_not_found')}
      </div>
    );
  }

  return (
    <ShareContext.Provider value={{ isSharedConvo: true }}>
      <main
        className="relative flex w-full grow overflow-hidden dark:bg-surface-secondary"
        style={{ paddingBottom: '50px' }}
      >
        <div className="transition-width relative flex h-full w-full flex-1 flex-col items-stretch overflow-hidden pt-0 dark:bg-surface-secondary">
          <div className="flex h-full flex-col text-text-primary" role="presentation">
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {content}
            </div>
            <div className="w-full border-t-0 pl-0 pt-2 touch-desktop:w-[calc(100%-.5rem)] touch-desktop:border-t-0 touch-desktop:border-transparent touch-desktop:pl-0 touch-desktop:pt-0 touch-desktop:dark:border-transparent">
              <Footer className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-center gap-2 bg-gradient-to-t from-surface-secondary to-transparent px-2 pb-2 pt-8 text-xs text-text-secondary touch-desktop:px-[60px]" />
            </div>
          </div>
        </div>
      </main>
    </ShareContext.Provider>
  );
}

export default memo(SharedView);
