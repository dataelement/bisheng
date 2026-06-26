import { useSearchParams } from 'react-router-dom';
import StandaloneChatPage from '~/pages/standaloneChat/StandaloneChatPage';

export default function PortalWorkflowChatPage() {
  const [searchParams] = useSearchParams();
  const chatId = searchParams.get('chat_id')?.trim() || '';

  return (
    <StandaloneChatPage
      mode="auth"
      flowType="workflow"
      hideSidebar
      forceNewChatOnLoad={!chatId}
      initialChatId={chatId}
    />
  );
}
